from django.middleware.csrf import get_token
from django.urls import reverse
from django.utils import timezone

from cabinet.models import BonusEvent

from .daily_tasks import build_daily_tasks_card
from .streaks import build_streak_card
from .xp import build_level_progress


DEFAULT_PROGRESS_STEPS = (
    {"label": "Заходите ежедневно", "is_done": False},
    {"label": "Выполняйте задания", "is_done": False},
    {"label": "Получайте бонусы", "is_done": False},
    {"label": "Открывайте новые уровни", "is_done": False},
)


BONUS_EVENT_ICONS = {
    BonusEvent.EventType.DAILY_TASK: "✓",
    BonusEvent.EventType.STREAK: "🔥",
    BonusEvent.EventType.ROULETTE: "🎁",
    BonusEvent.EventType.REFERRAL: "👥",
}


def _bonus_event_subtitle(event) -> str:
    if event.description:
        return event.description

    rewards = []
    if event.coin_delta:
        rewards.append(f"{event.coin_delta:+d} монет")
    if event.xp_delta:
        rewards.append(f"{event.xp_delta:+d} XP")
    if event.spin_delta:
        rewards.append(f"{event.spin_delta:+d} попыток")
    return " · ".join(rewards) or event.get_event_type_display()


def _serialize_bonus_event(event) -> dict:
    created_at = timezone.localtime(event.created_at)
    return {
        "title": event.title,
        "subtitle": _bonus_event_subtitle(event),
        "time_label": created_at.strftime("%d.%m, %H:%M"),
        "icon": BONUS_EVENT_ICONS.get(event.event_type, "🎁"),
    }


def _recent_bonus_events(user) -> tuple[list[dict], list[dict]]:
    recent_gifts = list(
        BonusEvent.objects.filter(user=user).order_by("-created_at", "-id")[:5]
    )
    recent_wins = list(
        BonusEvent.objects.filter(
            user=user,
            event_type=BonusEvent.EventType.ROULETTE,
        ).order_by("-created_at", "-id")[:3]
    )
    serialized_gifts = [_serialize_bonus_event(event) for event in recent_gifts]
    serialized_wins = [_serialize_bonus_event(event) for event in recent_wins]
    serialized_wins.extend([None] * (3 - len(serialized_wins)))
    return serialized_gifts, serialized_wins


def build_bonus_center_context(user, request=None) -> dict:
    """Build the bonus-center page context without template-side data access."""
    recent_gifts, recent_wins = _recent_bonus_events(user)
    daily_tasks_card = build_daily_tasks_card(user)
    streak_card = build_streak_card(user)
    level_progress = build_level_progress(user)

    return {
        "roulette_state_url": reverse("cabinet:roulette_state"),
        "roulette_spin_url": reverse("cabinet:roulette_spin"),
        "roulette_csrf_token": get_token(request) if request is not None else "",
        "next_bonus": {
            "title": "Следующий бонус",
            "subtitle": "Через",
            "countdown_label": "--:--:--",
            "status_label": "Загрузка состояния рулетки…",
            "description": "Возвращайтесь, чтобы снова крутить колесо и получать награды.",
        },
        "daily_tasks_card": daily_tasks_card,
        "streak_card": streak_card,
        "referral_card": {
            "title": "Бонус за рефералов",
            "subtitle": "Приглашайте друзей",
            "reward_label": "До 1000 монет",
            "description": "Приглашайте друзей и получайте дополнительные бонусы на баланс.",
        },
        "recent_wins": recent_wins,
        "recent_gifts": recent_gifts,
        "level_progress": {
            **level_progress,
            "steps": DEFAULT_PROGRESS_STEPS,
        },
        "levels_preview": level_progress["levels_preview"],
        "balance_cta": {
            "title": "Пополните баланс\nи получайте больше",
            "description": (
                "Чем больше монет на балансе — тем больше возможностей на платформе."
            ),
            "label": "Пополнить баланс",
            "url": f"{reverse('cabinet:profile')}?tab=wallet",
        },
    }
