from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from cabinet.models import BonusEvent, StreakReward, UserDailyStreak

from .bonus_rewards import grant_bonus_reward


def get_user_daily_streak(user) -> UserDailyStreak:
    state, _ = UserDailyStreak.objects.get_or_create(user=user)
    return state


@transaction.atomic
def touch_daily_streak(user, now=None) -> UserDailyStreak:
    now = now or timezone.now()
    today = timezone.localdate(now)

    locked_user = user.__class__.objects.select_for_update().get(pk=user.pk)
    state, _ = UserDailyStreak.objects.get_or_create(user=locked_user)
    state = UserDailyStreak.objects.select_for_update().get(pk=state.pk)

    if state.last_seen_date == today:
        return state

    yesterday = today - timedelta(days=1)
    if state.last_seen_date == yesterday:
        state.current_days += 1
    else:
        state.current_days = 1

    state.best_days = max(state.best_days, state.current_days)
    state.last_seen_date = today
    state.save(
        update_fields=(
            "current_days",
            "best_days",
            "last_seen_date",
            "updated_at",
        )
    )

    reward = (
        StreakReward.objects.filter(
            is_active=True,
            day_number=state.current_days,
        )
        .order_by("id")
        .first()
    )
    if reward is not None:
        grant_bonus_reward(
            locked_user,
            xp=reward.reward_xp,
            coins=reward.reward_coins,
            spins=reward.reward_spins,
            event_type=BonusEvent.EventType.STREAK,
            title=reward.title,
            description=f"Награда за {reward.day_number}-й день серии",
        )

    return state


def _days_label(days: int) -> str:
    days = int(days)
    if days % 10 == 1 and days % 100 != 11:
        word = "день"
    elif days % 10 in (2, 3, 4) and days % 100 not in (12, 13, 14):
        word = "дня"
    else:
        word = "дней"
    return f"{days} {word}"


def build_streak_card(user) -> dict:
    state = get_user_daily_streak(user)
    rewards = list(
        StreakReward.objects.filter(is_active=True)
        .order_by("day_number", "id")
    )

    max_preview_day = max(
        7,
        min(
            7,
            max((reward.day_number for reward in rewards), default=7),
        ),
    )
    day_numbers = [
        {
            "number": day,
            "is_reached": day <= state.current_days,
            "is_current": day == state.current_days,
        }
        for day in range(1, max_preview_day + 1)
    ]

    next_reward = next(
        (reward for reward in rewards if reward.day_number > state.current_days),
        None,
    )

    return {
        "title": "Серия дней",
        "subtitle": "Заходите ежедневно",
        "days_label": _days_label(state.current_days),
        "current_days": state.current_days,
        "best_days": state.best_days,
        "day_numbers": day_numbers,
        "next_reward_day": next_reward.day_number if next_reward is not None else None,
        "next_reward_title": next_reward.title if next_reward is not None else "",
    }
