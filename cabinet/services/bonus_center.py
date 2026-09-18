from django.middleware.csrf import get_token
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone

from cabinet.models import BonusEvent
from cabinet.roulette.history import RouletteSpin
from cabinet.roulette.models import RoulettePrize

from .daily_tasks import build_daily_tasks_card
from .referral_bonuses import build_referral_bonus_card
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


def _serialize_roulette_spin(spin) -> dict:
    spun_at = timezone.localtime(spin.spun_at)
    return {
        "title": spin.prize_title or "Подарок",
        "subtitle": spin.prize_short_text or spin.get_reward_type_display(),
        "time_label": spun_at.strftime("%d.%m, %H:%M"),
        "icon": "🎁",
    }


def _recent_bonus_content(user) -> tuple[list[dict], list[dict]]:
    events = list(
        BonusEvent.objects.filter(user=user)
        .select_related("user")
        .order_by("-created_at", "-id")[:5]
    )
    spins = list(
        RouletteSpin.objects.filter(user=user)
        .exclude(reward_type=RoulettePrize.RewardType.NOTHING)
        .select_related("user")
        .order_by("-spun_at", "-id")[:3]
    )

    recent_gifts = [_serialize_bonus_event(event) for event in events]
    recent_wins = [_serialize_roulette_spin(spin) for spin in spins]
    recent_wins.extend([None] * (3 - len(recent_wins)))
    return recent_gifts, recent_wins


def build_bonus_center_context(user, request=None) -> dict:
    """Build the complete bonus-center context without template-side data access."""
    recent_gifts, recent_wins = _recent_bonus_content(user)
    daily_tasks_card = build_daily_tasks_card(user)
    streak_card = build_streak_card(user)
    referral_card = build_referral_bonus_card(user, request=request)
    level_progress = build_level_progress(user)

    return {
        "roulette_state_url": reverse("cabinet:roulette_state"),
        "roulette_spin_url": reverse("cabinet:roulette_spin"),
        "roulette_bg": static("front/img/login.png"),
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
        "referral_card": referral_card,
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
