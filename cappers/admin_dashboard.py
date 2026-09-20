from django.contrib.admin.models import LogEntry
from django.urls import NoReverseMatch, reverse


ADMIN_APP_GROUPS = {
    "back": {"title": "Backend", "subtitle": "Серверная часть", "icon": "database", "color": "blue"},
    "front": {"title": "Front", "subtitle": "Веб-интерфейс", "icon": "monitor", "color": "blue"},
    "cabinet": {"title": "Cabinet", "subtitle": "Пользователи", "icon": "user", "color": "green"},
    "notifications": {"title": "Уведомления", "subtitle": "Сообщения и алерты", "icon": "bell", "color": "red"},
    "bots": {"title": "Боты", "subtitle": "Telegram и другое", "icon": "bot", "color": "purple"},
    "game": {"title": "Игры", "subtitle": "Игровые модули", "icon": "gamepad", "color": "violet"},
    "wallets": {"title": "Кошелёк", "subtitle": "Платежи и балансы", "icon": "wallet", "color": "green"},
    "django_celery_beat": {
        "title": "Периодические задачи",
        "subtitle": "Запланированные задачи",
        "icon": "clock",
        "color": "orange",
    },
    "pages": {"title": "Страницы", "subtitle": "Контент сайта", "icon": "file", "color": "yellow"},
    "seo": {"title": "SEO", "subtitle": "Метатеги и аналитика", "icon": "search", "color": "yellow"},
    "achievements": {
        "title": "Достижения",
        "subtitle": "Бейджи и условия",
        "icon": "award",
        "color": "cyan",
    },
}

SEO_MODEL_OBJECT_NAMES = {"PageSEO"}

ADMIN_APP_GROUP_SOURCES = {
    "cabinet": ("cabinet", "auth"),
    "notifications": ("notifications", "account_email"),
    "game": ("game", "tournaments"),
}


def _copy_models(app):
    app_label = app["app_label"]
    return [
        {
            **model,
            "source_app_label": app_label,
        }
        for model in app.get("models", [])
    ]


def _build_dashboard_apps(app_list):
    apps_by_label = {
        app["app_label"]: {
            **app,
            "models": _copy_models(app),
        }
        for app in app_list
    }

    page_app = apps_by_label.get("pages")
    seo_models = []
    if page_app:
        seo_models = [
            model
            for model in page_app["models"]
            if model.get("object_name") in SEO_MODEL_OBJECT_NAMES
        ]
        page_app["models"] = [
            model
            for model in page_app["models"]
            if model.get("object_name") not in SEO_MODEL_OBJECT_NAMES
        ]

    dashboard_apps = []
    used_labels = set()

    for key, config in ADMIN_APP_GROUPS.items():
        if key == "seo":
            if not seo_models:
                continue
            models = seo_models
            app_url = models[0].get("admin_url", "")
            source_app_label = "pages"
        else:
            source_labels = ADMIN_APP_GROUP_SOURCES.get(key, (key,))
            source_apps = [
                apps_by_label[label]
                for label in source_labels
                if label in apps_by_label
            ]
            if not source_apps:
                continue

            used_labels.update(source_labels)
            models = [
                model
                for source_app in source_apps
                for model in source_app["models"]
            ]
            if not models:
                continue

            primary_app = apps_by_label.get(key) or source_apps[0]
            app_url = primary_app.get("app_url", "")
            source_app_label = key

        dashboard_apps.append(
            {
                "key": key,
                "source_app_label": source_app_label,
                "title": config["title"],
                "subtitle": config["subtitle"],
                "icon": config["icon"],
                "color": config["color"],
                "model_count": len(models),
                "app_url": app_url,
                "models": models,
            }
        )

    for app_label, app in apps_by_label.items():
        if app_label in used_labels or app_label == "pages":
            continue
        models = app["models"]
        if not models:
            continue
        dashboard_apps.append(
            {
                "key": app_label,
                "source_app_label": app_label,
                "title": app["name"],
                "subtitle": app_label,
                "icon": "grid",
                "color": "blue",
                "model_count": len(models),
                "app_url": app.get("app_url", ""),
                "models": models,
            }
        )

    return dashboard_apps


def _build_quick_actions(request):
    actions = (
        {
            "permission": "cabinet.add_user",
            "title": "Добавить пользователя",
            "subtitle": "Новая учетная запись",
            "icon": "user",
            "url_name": "admin:cabinet_user_add",
        },
        {
            "permission": "achievements.add_achievement",
            "title": "Новое достижение",
            "subtitle": "Настроить награду",
            "icon": "award",
            "url_name": "admin:achievements_achievement_add",
        },
        {
            "permission": "pages.view_promobanner",
            "title": "Промо-баннеры",
            "subtitle": "Управление рекламой",
            "icon": "file",
            "url_name": "admin:pages_promobanner_changelist",
        },
        {
            "permission": "game.view_predictioncoupon",
            "title": "Прогнозы",
            "subtitle": "Открыть купоны",
            "icon": "gamepad",
            "url_name": "admin:game_predictioncoupon_changelist",
        },
    )

    result = []
    for action in actions:
        if not request.user.has_perm(action["permission"]):
            continue
        try:
            url = reverse(action["url_name"])
        except NoReverseMatch:
            continue
        result.append(
            {
                "title": action["title"],
                "subtitle": action["subtitle"],
                "icon": action["icon"],
                "url": url,
            }
        )
    return result


def _build_recent_actions(request):
    if not request.user.is_authenticated:
        return []

    entries = (
        LogEntry.objects.filter(user=request.user)
        .select_related("content_type")
        .order_by("-action_time", "-id")[:8]
    )

    result = []
    for entry in entries:
        result.append(
            {
                "object_repr": entry.object_repr,
                "url": None if entry.is_deletion() else entry.get_admin_url(),
                "content_type": entry.content_type.name if entry.content_type_id else "",
                "action_time": entry.action_time,
            }
        )
    return result


def build_admin_dashboard_context(request, app_list):
    return {
        "dashboard_apps": _build_dashboard_apps(app_list),
        "quick_actions": _build_quick_actions(request),
        "recent_actions": _build_recent_actions(request),
    }
