from django.core.exceptions import ValidationError
from django.db import transaction

from cabinet.models import UserXpState, XpLevel


def get_user_xp_state(user) -> UserXpState:
    state, _ = UserXpState.objects.get_or_create(user=user)
    return state


def _level_for_xp(levels, xp: int):
    current = None
    for level in levels:
        if level.required_xp > xp:
            break
        current = level
    return current


@transaction.atomic
def sync_user_level(user_or_state) -> UserXpState:
    if isinstance(user_or_state, UserXpState):
        state = UserXpState.objects.select_for_update().get(pk=user_or_state.pk)
    else:
        user = user_or_state
        user.__class__.objects.select_for_update().get(pk=user.pk)
        state, _ = UserXpState.objects.get_or_create(user=user)
        state = UserXpState.objects.select_for_update().get(pk=state.pk)

    levels = list(
        XpLevel.objects.filter(is_active=True).order_by("required_xp", "level", "id")
    )
    matched_level = _level_for_xp(levels, state.xp)
    level_number = matched_level.level if matched_level is not None else 1

    if state.level != level_number:
        state.level = level_number
        state.save(update_fields=("level", "updated_at"))

    return state


@transaction.atomic
def grant_xp(user, amount: int, related_obj=None, note="") -> UserXpState:
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

    # related_obj and note are accepted for a common reward-service signature.
    # The bonus journal is written by grant_bonus_reward(), so XP is not logged twice.
    return sync_user_level(state)


def build_level_progress(user) -> dict:
    state = get_user_xp_state(user)
    levels = list(
        XpLevel.objects.filter(is_active=True).order_by("required_xp", "level", "id")
    )

    matched_level = _level_for_xp(levels, state.xp)
    level_number = matched_level.level if matched_level is not None else 1
    if state.level != level_number:
        UserXpState.objects.filter(pk=state.pk).update(level=level_number)
        state.level = level_number

    current_level = matched_level
    if current_level is None:
        current_level = next(
            (level for level in levels if level.level == state.level),
            None,
        )

    current_level_xp = (
        int(current_level.required_xp)
        if current_level is not None and current_level.required_xp <= state.xp
        else 0
    )
    next_level = next(
        (level for level in levels if level.required_xp > state.xp),
        None,
    )

    if next_level is None:
        next_level_xp = None
        progress_percent = 100
        xp_to_next_level = 0
    else:
        next_level_xp = int(next_level.required_xp)
        level_span = max(1, next_level_xp - current_level_xp)
        earned_in_level = max(0, int(state.xp) - current_level_xp)
        progress_percent = min(100, int((earned_in_level * 100) / level_span))
        xp_to_next_level = max(0, next_level_xp - int(state.xp))

    current_index = next(
        (index for index, level in enumerate(levels) if level.level == state.level),
        0,
    )
    preview_start = max(0, current_index - 2)
    preview_levels = levels[preview_start : preview_start + 5]
    levels_preview = [
        {
            "level": level.level,
            "title": level.title,
            "required_xp": int(level.required_xp),
            "is_current": level.level == state.level,
            "is_unlocked": state.xp >= level.required_xp,
        }
        for level in preview_levels
    ]

    return {
        "level": state.level,
        "level_title": current_level.title if current_level is not None else f"Уровень {state.level}",
        "xp": int(state.xp),
        "current_level_xp": current_level_xp,
        "next_level_xp": next_level_xp,
        "progress_percent": progress_percent,
        "xp_to_next_level": xp_to_next_level,
        "levels_preview": levels_preview,
    }
