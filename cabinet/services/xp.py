from django.core.exceptions import ValidationError
from django.db import transaction

from cabinet.models import UserXpState


@transaction.atomic
def grant_xp(user, amount: int) -> UserXpState:
    try:
        amount = int(amount)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Количество XP должно быть целым числом.") from exc

    if amount <= 0:
        raise ValidationError("Количество XP для начисления должно быть больше нуля.")

    locked_user = user.__class__.objects.select_for_update().get(pk=user.pk)
    state, _ = UserXpState.objects.get_or_create(user=locked_user)
    state = UserXpState.objects.select_for_update().get(pk=state.pk)
    state.xp += amount
    state.save(update_fields=("xp", "updated_at"))
    return state
