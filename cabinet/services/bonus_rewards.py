from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse

from cabinet.models import BonusEvent
from cabinet.roulette.services import get_user_roulette_state
from notifications.models import Notification
from notifications.services import create_notification
from wallets.models import CoinTransaction
from wallets.services import credit_coins

from .xp import grant_xp


COIN_KIND_BY_EVENT_TYPE = {
    BonusEvent.EventType.DAILY_TASK: CoinTransaction.Kind.DAILY_TASK_REWARD,
    BonusEvent.EventType.ROULETTE: CoinTransaction.Kind.ROULETTE_REWARD,
}

NOTIFICATION_BY_EVENT_TYPE = {
    BonusEvent.EventType.DAILY_TASK: (
        Notification.Kind.BONUS_DAILY_TASK,
        "cabinet:bonus_tasks",
    ),
    BonusEvent.EventType.STREAK: (
        Notification.Kind.BONUS_STREAK,
        "cabinet:bonuses",
    ),
    BonusEvent.EventType.ROULETTE: (
        Notification.Kind.BONUS_ROULETTE,
        "cabinet:bonuses",
    ),
    BonusEvent.EventType.REFERRAL: (
        Notification.Kind.BONUS_REFERRAL,
        "cabinet:referrals",
    ),
}


def _non_negative_int(value, label: str) -> int:
    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{label} должно быть целым числом.") from exc

    if value < 0:
        raise ValidationError(f"{label} не может быть отрицательным.")
    return value


def _bonus_notification_message(*, xp: int, coins: int, spins: int, description: str) -> str:
    parts = []
    if xp:
        parts.append(f"+{xp} XP")
    if coins:
        parts.append(f"+{coins} монет")
    if spins:
        parts.append(f"+{spins} попыток")
    if description:
        parts.append(description)
    return " · ".join(parts)


def _related_subject(related_obj) -> tuple[str, int | None]:
    if related_obj is None:
        return "", None
    return related_obj._meta.label_lower, related_obj.pk


@transaction.atomic
def grant_bonus_reward(
    user,
    *,
    xp=0,
    coins=0,
    spins=0,
    event_type,
    title,
    description="",
    related_obj=None,
) -> BonusEvent:
    xp = _non_negative_int(xp, "Количество XP")
    coins = _non_negative_int(coins, "Количество коинов")
    spins = _non_negative_int(spins, "Количество попыток")

    if event_type not in BonusEvent.EventType.values:
        raise ValidationError("Неизвестный тип бонусного события.")
    if not title:
        raise ValidationError("Укажите название бонусного события.")

    locked_user = user.__class__.objects.select_for_update().get(pk=user.pk)

    if xp:
        grant_xp(
            locked_user,
            xp,
            related_obj=related_obj,
            note=description or title,
        )

    if coins:
        credit_coins(
            locked_user,
            coins,
            COIN_KIND_BY_EVENT_TYPE.get(event_type, CoinTransaction.Kind.ADJUSTMENT),
            related_obj=related_obj,
            note=description or title,
        )

    if spins:
        get_user_roulette_state(locked_user).grant_spins(spins)

    related_model, related_id = _related_subject(related_obj)
    event = BonusEvent.objects.create(
        user=locked_user,
        event_type=event_type,
        title=title,
        description=description,
        xp_delta=xp,
        coin_delta=coins,
        spin_delta=spins,
        related_model=related_model,
        related_id=related_id,
    )

    notification_config = NOTIFICATION_BY_EVENT_TYPE.get(event_type)
    if notification_config is not None:
        notification_kind, url_name = notification_config
        notification_title = (
            "Награда получена"
            if event_type == BonusEvent.EventType.DAILY_TASK
            else title
        )
        notification_message = _bonus_notification_message(
            xp=xp,
            coins=coins,
            spins=spins,
            description=description,
        )
        if event_type == BonusEvent.EventType.DAILY_TASK:
            notification_message = " · ".join(
                part
                for part in (title, notification_message)
                if part
            )

        create_notification(
            recipient=locked_user,
            kind=notification_kind,
            title=notification_title,
            message=notification_message,
            url=reverse(url_name),
            event_key=f"bonus:{event.pk}",
            meta={
                "bonus_event_id": event.pk,
                "xp_delta": xp,
                "coin_delta": coins,
                "spin_delta": spins,
            },
        )

    return event
