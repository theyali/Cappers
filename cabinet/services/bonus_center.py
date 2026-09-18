from django.middleware.csrf import get_token
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone

from cabinet.models import BonusEvent
from cabinet.roulette.history import RouletteSpin
from cabinet.roulette.models import RoulettePrize
from cabinet.roulette.services import get_user_roulette_state

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


def _recent_bonus_events(user) -> list[dict]:
    events = list(
        BonusEvent.objects.filter(user=user)
        .select_related("user")
        .order_by("-created_at", "-id")[:5]
    )
    return [_serialize_bonus_event(event) for event in events]


def _recent_roulette_wins(user) -> list[dict]:
    spins = list(
        RouletteSpin.objects.filter(user=user)
        .exclude(reward_type=RoulettePrize.RewardType.NOTHING)
        .select_related("user")
        .order_by("-spun_at", "-id")[:3]
    )
    recent_wins = [_serialize_roulette_spin(spin) for spin in spins]
    recent_wins.extend([None] * (3 - len(recent_wins)))
    return recent_wins


def _recent_bonus_content(user) -> tuple[list[dict], list[dict]]:
    return _recent_bonus_events(user), _recent_roulette_wins(user)


def _prepare_daily_tasks_card(card: dict) -> dict:
    claimable_task = next(
        (task for task in card["tasks"] if task["can_claim"]),
        None,
    )
    return {
        **card,
        "summary_label": f"{card['completed']} из {card['total']} выполнено",
        "progress_aria_label": "Прогресс ежедневных заданий",
        "arrow_label": "›",
        "claim_url": (
            reverse("cabinet:daily_task_claim", args=(claimable_task["id"],))
            if claimable_task is not None
            else ""
        ),
        "claim_button_label": (
            "Получить"
            if card["claimable_count"] <= 1
            else f"Получить · {card['claimable_count']}"
        ),
        "claim_pending_label": "Получаем…",
        "claim_error_label": "Не удалось получить награду.",
    }


def _prepare_level_progress(progress: dict) -> dict:
    percent = max(0, min(100, int(progress["progress_percent"])))
    progress_length = round(302 * percent / 100)
    return {
        **progress,
        "steps": DEFAULT_PROGRESS_STEPS,
        "badge_label": f"Ур. {progress['level']}",
        "aria_label": f"Прогресс уровня {percent}%",
        "target_label": (
            f"из {progress['next_level_xp']}"
            if progress["next_level_xp"]
            else "макс."
        ),
        "status_label": (
            f"{progress['xp_to_next_level']} XP до следующего уровня"
            if progress["next_level_xp"]
            else "Максимальный уровень"
        ),
        "progress_dasharray": f"{progress_length} 302",
    }


def build_bonus_reward_update_context(user) -> dict:
    roulette_state = get_user_roulette_state(user)
    return {
        "daily_tasks_card": _prepare_daily_tasks_card(build_daily_tasks_card(user)),
        "level_progress": _prepare_level_progress(build_level_progress(user)),
        "recent_gifts": _recent_bonus_events(user),
        "available_spins": roulette_state.available_spins,
    }


def build_bonus_center_context(user, request=None) -> dict:
    """Build the complete bonus-center context without template-side data access."""
    recent_gifts, recent_wins = _recent_bonus_content(user)
    daily_tasks_card = build_daily_tasks_card(user)
    streak_card = build_streak_card(user)
    referral_card = build_referral_bonus_card(user, request=request)
    level_progress = build_level_progress(user)

    next_bonus = {
        "title": "Следующий бонус",
        "subtitle": "Через",
        "countdown_label": "--:--:--",
        "status_label": "Загрузка состояния рулетки…",
        "description": "Возвращайтесь, чтобы снова крутить колесо и получать награды.",
        "value_label": "--:--:--",
        "icon_kind": "clock",
        "icon_tone": "blue",
        "is_countdown": True,
        "arrow_label": "›",
    }
    daily_tasks_card = _prepare_daily_tasks_card(daily_tasks_card)
    streak_card = {
        **streak_card,
        "days_aria_label": "Дни серии",
        "arrow_label": "›",
    }
    referral_card = {
        **referral_card,
        "value_label": referral_card["reward_label"],
        "icon_kind": "referral",
        "icon_tone": "blue",
        "is_countdown": False,
        "arrow_label": "›",
        "url": referral_card["referral_url"],
    }

    levels_preview = [
        {
            **level,
            "label": f"Уровень {level['level']}",
        }
        for level in level_progress["levels_preview"]
    ]
    level_progress = _prepare_level_progress(level_progress)

    return {
        "roulette_state_url": reverse("cabinet:roulette_state"),
        "roulette_spin_url": reverse("cabinet:roulette_spin"),
        "roulette_bg": static("front/img/login.png"),
        "roulette_csrf_token": get_token(request) if request is not None else "",
        "bonus_page": {
            "title": "Мои бонусы — КапперХаб",
            "mobile_nav_label": "Разделы профиля на мобильных устройствах",
            "profile_nav_label": "Разделы профиля",
            "aside_label": "Бонусный центр",
            "hero": {
                "title": "Бонусы каждый день",
                "title_prefix": "с",
                "brand": "КапперХаб",
                "description": (
                    "Получайте бесплатные прогнозы, бонусы на баланс, VIP-доступ "
                    "и другие награды. Заходите каждый день и увеличивайте свои шансы."
                ),
                "countdown_caption": "До следующей попытки",
                "canvas_label": "Ежедневная рулетка бонусов. Нажмите, чтобы крутить.",
                "canvas_fallback": "Ваш браузер не поддерживает canvas.",
            },
            "recent_wins": {
                "title": "Последние выигрыши",
                "subtitle": "Результаты рулетки",
                "fallback_title": "Подарок",
                "fallback_subtitle": "Выигрыш рулетки",
                "fallback_icon": "🎁",
            },
            "levels": {
                "title": "Мои уровни",
                "subtitle": "Прогресс активности",
            },
            "recent_gifts": {
                "title": "Последние подарки",
                "all_label": "Все",
                "empty_title": "Подарков пока нет",
                "empty_description": "Новые бонусы появятся здесь.",
                "empty_icon": "🎁",
            },
            "progress": {
                "title": "Прогресс к большему",
                "star_label": "★",
            },
        },
        "next_bonus": next_bonus,
        "daily_tasks_card": daily_tasks_card,
        "streak_card": streak_card,
        "referral_card": referral_card,
        "recent_wins": recent_wins,
        "recent_gifts": recent_gifts,
        "level_progress": level_progress,
        "levels_preview": levels_preview,
        "balance_cta": {
            "title": "Пополните баланс\nи получайте больше",
            "description": (
                "Чем больше монет на балансе — тем больше возможностей на платформе."
            ),
            "label": "Пополнить баланс",
            "url": f"{reverse('cabinet:profile')}?tab=wallet",
            "arrow_label": "→",
        },
    }
