from django.middleware.csrf import get_token
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone

from cabinet.models import BonusEvent, XpLevel
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
    return {
        **card,
        "summary_label": f"Сегодня выполнено {card['completed']} из {card['total']}",
        "progress_aria_label": "Прогресс ежедневных заданий",
        "arrow_label": "›",
        "claim_url": (
            reverse("cabinet:daily_tasks_claim_all")
            if card["claimable_count"] > 0
            else ""
        ),
        "claim_button_label": "Получить все",
        "claim_pending_label": "Получаем…",
        "claim_error_label": "Не удалось получить награду.",
    }


def _prepare_daily_task_items(card: dict) -> list[dict]:
    tasks = []
    for task in card["tasks"]:
        tasks.append(
            {
                **task,
                "progress_percent": min(
                    100,
                    int(
                        (task["current_value"] * 100)
                        / max(1, task["target_value"])
                    ),
                ),
                "progress_label": (
                    f'{task["current_value"]} / {task["target_value"]}'
                ),
                "row_class": (
                    "is-completed"
                    if task["is_completed"]
                    else "is-in-progress"
                ),
                "status_class": (
                    "is-completed"
                    if task["is_completed"]
                    else "is-in-progress"
                ),
                "display_status_label": (
                    "Выполнено"
                    if task["is_completed"]
                    else "В процессе"
                ),
                "claim_url": reverse(
                    "cabinet:daily_task_claim",
                    kwargs={"task_id": task["id"]},
                ),
            }
        )
    return tasks


def _prepare_streak_card(card: dict) -> dict:
    return {
        **card,
        "days_aria_label": "Дни серии",
        "arrow_label": "›",
    }


def _prepare_level_progress(progress: dict) -> dict:
    percent = max(0, min(100, int(progress["progress_percent"])))
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
    }


def build_bonus_live_state(user, roulette_state=None) -> dict:
    roulette_state = roulette_state or get_user_roulette_state(user)
    return {
        "daily_tasks_summary": _prepare_daily_tasks_card(
            build_daily_tasks_card(user)
        ),
        "streak": _prepare_streak_card(build_streak_card(user)),
        "level_progress": _prepare_level_progress(build_level_progress(user)),
        "recent_gifts": _recent_bonus_events(user),
        "available_spins": roulette_state.available_spins,
    }


def build_bonus_reward_update_context(user) -> dict:
    live_state = build_bonus_live_state(user)
    return {
        "daily_tasks_card": live_state["daily_tasks_summary"],
        "streak": live_state["streak"],
        "level_progress": live_state["level_progress"],
        "recent_gifts": live_state["recent_gifts"],
        "available_spins": live_state["available_spins"],
    }



def build_profile_bonus_summary(user) -> dict:
    """Build the compact bonus summary used on the profile overview tab."""
    daily_tasks_card = build_daily_tasks_card(user)
    daily_tasks_card = {
        **_prepare_daily_tasks_card(daily_tasks_card),
        "tasks": _prepare_daily_task_items(daily_tasks_card),
    }
    level_progress = _prepare_level_progress(build_level_progress(user))
    streak_card = _prepare_streak_card(build_streak_card(user))
    current_level = (
        XpLevel.objects.filter(
            is_active=True,
            level=level_progress["level"],
        )
        .only("icon", "image")
        .first()
    )
    hero = {
        "current_level_title": level_progress["level_title"],
        "current_level_number": level_progress["level"],
        "xp": level_progress["xp"],
        "target_label": level_progress["target_label"],
        "status_label": level_progress["status_label"],
        "progress_class": level_progress["progress_class"],
        "icon_url": (
            current_level.icon.url
            if current_level is not None and current_level.icon
            else ""
        ),
        "image_url": (
            current_level.image.url
            if current_level is not None and current_level.image
            else ""
        ),
    }

    return {
        "hero": hero,
        "daily_tasks": daily_tasks_card["tasks"],
        "daily_tasks_title": "Ежедневные задания",
        "daily_tasks_empty_title": "Заданий пока нет",
        "daily_tasks_empty_description": "Новые задания появятся здесь",
        "tasks_summary_label": daily_tasks_card["summary_label"],
        "tasks_url": reverse("cabinet:bonus_tasks"),
        "tasks_link_label": "Все задания",
        "tasks_claim_url": daily_tasks_card["claim_url"],
        "tasks_claim_label": daily_tasks_card["claim_button_label"],
        "tasks_claim_pending_label": daily_tasks_card["claim_pending_label"],
        "tasks_claim_error_label": daily_tasks_card["claim_error_label"],
        "level_progress": {
            **level_progress,
            "title": "Прогресс уровня",
            "star_label": "★",
            "link_label": "Открыть уровни",
            "arrow_label": "→",
        },
        "levels_url": reverse("cabinet:bonus_levels"),
        "streak_card": streak_card,
        "bonuses_url": reverse("cabinet:bonuses"),
        "bonuses_label": "Все бонусы",
        "notifications_url": reverse("notifications:center"),
        "notifications_label": "Настроить уведомления",
        "link_arrow_label": "→",
    }


def build_bonus_tasks_page_context(user, request=None) -> dict:
    """Build the minimal SSR context for the daily tasks page."""
    daily_tasks_card = build_daily_tasks_card(user)
    tasks = _prepare_daily_task_items(daily_tasks_card)

    daily_tasks_card = {
        **_prepare_daily_tasks_card(daily_tasks_card),
        "tasks": tasks,
    }

    return {
        "page": {
            "title": "Ежедневные задания — КапперХаб",
            "heading": "Ежедневные задания",
            "description": daily_tasks_card["description"],
            "mobile_nav_label": "Разделы профиля на мобильных устройствах",
            "profile_nav_label": "Разделы профиля",
        },
        "daily_tasks_card": daily_tasks_card,
        "tasks": tasks,
    }


def build_bonus_levels_page_context(user, request=None) -> dict:
    """Build the SSR context for the bonus levels page."""
    level_progress = _prepare_level_progress(build_level_progress(user))
    levels = list(
        XpLevel.objects.filter(is_active=True)
        .order_by("required_xp", "level", "id")
    )

    current_level_number = level_progress["level"]
    current_progress_percent = max(
        0,
        min(100, int(level_progress["progress_percent"])),
    )

    level_items = []
    for level in levels:
        required_xp = int(level.required_xp)
        is_current = level.level == current_level_number
        is_unlocked = level.level < current_level_number
        is_locked = level.level > current_level_number
        is_next = (
            is_locked
            and level_progress["next_level_xp"] is not None
            and required_xp == level_progress["next_level_xp"]
        )

        if is_current:
            status = "current"
            status_label = "Текущий"
            progress_percent = current_progress_percent
        elif is_unlocked:
            status = "unlocked"
            status_label = "Открыт"
            progress_percent = 100
        else:
            status = "locked"
            status_label = "Впереди"
            progress_percent = 0

        progress_bucket = min(
            100,
            max(0, ((progress_percent + 5) // 10) * 10),
        )

        rewards = []
        if level.reward_coins:
            rewards.append(f"+{level.reward_coins} монет")
        if level.reward_spins:
            rewards.append(f"+{level.reward_spins} попыток")

        level_items.append(
            {
                "level": level.level,
                "title": level.title,
                "description": level.description,
                "icon_url": level.icon.url if level.icon else "",
                "image_url": level.image.url if level.image else "",
                "required_xp": required_xp,
                "required_xp_label": f"{required_xp} XP",
                "reward_label": " · ".join(rewards) or "Без награды",
                "is_current": is_current,
                "is_unlocked": is_unlocked,
                "is_locked": is_locked,
                "is_next": is_next,
                "status": status,
                "status_label": status_label,
                "progress_percent": progress_percent,
                "progress_class": f"is-progress-{progress_bucket}",
            }
        )

    return {
        "page": {
            "title": "Уровни и XP — КапперХаб",
            "heading": "Уровни и XP",
            "description": (
                "Повышайте уровень активности, набирайте XP и открывайте новые награды."
            ),
            "mobile_nav_label": "Разделы профиля на мобильных устройствах",
            "profile_nav_label": "Разделы профиля",
        },
        "level_progress": level_progress,
        "levels": level_items,
        "recent_gifts": _recent_bonus_events(user),
        "daily_tasks_card": _prepare_daily_tasks_card(build_daily_tasks_card(user)),
        "streak_card": _prepare_streak_card(build_streak_card(user)),
    }


def build_bonus_center_context(user, request=None) -> dict:
    """Build the complete bonus-center context without template-side data access."""
    recent_gifts, recent_wins = _recent_bonus_content(user)
    daily_tasks_card = build_daily_tasks_card(user)
    streak_card = build_streak_card(user)
    referral_card = build_referral_bonus_card(user, request=request)
    level_progress = build_level_progress(user)
    notification_settings_url = reverse("notifications:center")

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
    daily_tasks_card = {
        **_prepare_daily_tasks_card(daily_tasks_card),
        "url": reverse("cabinet:bonus_tasks"),
        "link_label": "Открыть ежедневные задания",
    }
    streak_card = _prepare_streak_card(streak_card)
    referral_card = {
        **referral_card,
        "value_label": referral_card["reward_label"],
        "icon_kind": "referral",
        "icon_tone": "blue",
        "is_countdown": False,
        "arrow_label": "›",
        "url": reverse("cabinet:referrals"),
        "link_label": "Открыть реферальные бонусы",
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
        "notification_settings_url": notification_settings_url,
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
                "url": reverse("cabinet:bonus_levels"),
                "link_label": "Открыть уровни",
                "arrow_label": "›",
            },
            "side_tasks": {
                "title": "Актуальные задания",
                "all_label": "Все",
                "empty_title": "Заданий пока нет",
                "empty_description": "Новые задания появятся здесь.",
                "empty_icon": "✓",
            },
            "progress": {
                "title": "Прогресс к большему",
                "star_label": "★",
            },
            "notification_settings": {
                "label": "Настроить уведомления",
                "url": notification_settings_url,
                "arrow_label": "→",
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
