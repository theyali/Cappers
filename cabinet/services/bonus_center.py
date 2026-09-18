from django.middleware.csrf import get_token
from django.urls import reverse

from .daily_tasks import daily_tasks_for_user


DEFAULT_LEVELS_PREVIEW = (
    {"level": 1, "title": "Новичок"},
    {"level": 2, "title": "Активный"},
    {"level": 3, "title": "Эксперт"},
    {"level": 4, "title": "Профи"},
    {"level": 5, "title": "Легенда"},
)

DEFAULT_PROGRESS_STEPS = (
    {"label": "Заходите ежедневно", "is_done": False},
    {"label": "Выполняйте задания", "is_done": False},
    {"label": "Получайте бонусы", "is_done": False},
    {"label": "Открывайте новые уровни", "is_done": False},
)


def build_bonus_center_context(user, request=None) -> dict:
    """Build the bonus-center page context without template-side data access."""
    daily_tasks = list(daily_tasks_for_user(user))
    daily_tasks_total = len(daily_tasks)

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
        "daily_tasks_card": {
            "title": "Ежедневные задания",
            "completed": 0,
            "total": daily_tasks_total,
            "progress_slots": tuple(range(daily_tasks_total)),
            "description": "Выполняйте простые задания и получайте дополнительные бонусы.",
        },
        "streak_card": {
            "title": "Серия дней",
            "subtitle": "Заходите ежедневно",
            "days_label": "— дней",
            "day_numbers": tuple(range(1, 8)),
        },
        "referral_card": {
            "title": "Бонус за рефералов",
            "subtitle": "Приглашайте друзей",
            "reward_label": "До 1000 монет",
            "description": "Приглашайте друзей и получайте дополнительные бонусы на баланс.",
        },
        "recent_wins": (None, None, None),
        "recent_gifts": (None, None, None, None, None),
        "level_progress": {
            "level": 1,
            "current": 0,
            "target": 5,
            "xp_to_next_label": "— XP до следующего уровня",
            "steps": DEFAULT_PROGRESS_STEPS,
        },
        "levels_preview": DEFAULT_LEVELS_PREVIEW,
        "balance_cta": {
            "title": "Пополните баланс\nи получайте больше",
            "description": (
                "Чем больше монет на балансе — тем больше возможностей на платформе."
            ),
            "label": "Пополнить баланс",
            "url": f"{reverse('cabinet:profile')}?tab=wallet",
        },
    }
