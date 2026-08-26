from django.db import migrations


PUBLIC_PAGES = (
    (
        "Главная",
        "front:index",
        "КапперХаб — спортивная аналитика, прогнозы и эксперты",
        "Матчи, спортивная аналитика, публичные профили экспертов, рейтинги и статьи на одной платформе.",
        "index,follow",
    ),
    (
        "Все прогнозы",
        "front:predictions",
        "Спортивные прогнозы и аналитика — КапперХаб",
        "Лента опубликованных спортивных прогнозов и аналитических материалов с удобной навигацией по матчам.",
        "index,follow",
    ),
    (
        "Статьи",
        "front:articles",
        "Статьи о спорте и аналитике — КапперХаб",
        "Новые статьи, разборы матчей и материалы редакции КапперХаб.",
        "index,follow",
    ),
    ("Статья", "front:article_detail", "", "", "index,follow"),
    ("Публичный профиль эксперта", "front:expert_profile", "", "", "index,follow"),
    (
        "Статистика экспертов",
        "front:cappers_stats",
        "Рейтинг спортивных экспертов — КапперХаб",
        "Сравнение публичных профилей экспертов по активности, публикациям, аудитории и статистике.",
        "index,follow",
    ),
    (
        "Как пользоваться",
        "front:how_it_works",
        "Как пользоваться КапперХаб",
        "Инструкция по основным разделам, профилям экспертов, матчам, ленте и возможностям платформы.",
        "index,follow",
    ),
    ("Статическая страница", "front:static_page", "", "", "index,follow"),
    (
        "Список матчей",
        "game:match_list",
        "Футбольные матчи — расписание и данные | КапперХаб",
        "Список футбольных матчей со статусами, временем начала и основной информацией.",
        "index,follow",
    ),
    ("Страница матча", "game:match_detail", "", "", "index,follow"),
    ("Прогнозы на матч", "game:match_predictions", "", "", "index,follow"),
)

NOINDEX_PAGES = (
    ("Моя лента", "front:following_feed"),
    ("Избранное", "front:favorites"),
    ("Вход", "cabinet:login"),
    ("Регистрация", "cabinet:register"),
    ("Восстановление пароля", "cabinet:password_reset"),
    ("Пароль — письмо отправлено", "cabinet:password_reset_done"),
    ("Установка нового пароля", "cabinet:password_reset_confirm"),
    ("Пароль восстановлен", "cabinet:password_reset_complete"),
    ("Личный кабинет", "cabinet:profile"),
    ("Купон в личном кабинете", "cabinet:coupon_detail"),
)


def seed_page_seo(apps, schema_editor):
    PageSEO = apps.get_model("pages", "PageSEO")
    for name, route_name, title, description, robots in PUBLIC_PAGES:
        PageSEO.objects.update_or_create(
            route_name=route_name,
            exact_path="",
            defaults={
                "name": name,
                "meta_title": title,
                "meta_description": description,
                "robots": robots,
                "is_active": True,
            },
        )

    for name, route_name in NOINDEX_PAGES:
        PageSEO.objects.update_or_create(
            route_name=route_name,
            exact_path="",
            defaults={
                "name": name,
                "robots": "noindex,follow",
                "is_active": True,
            },
        )


def reverse_seed(apps, schema_editor):
    PageSEO = apps.get_model("pages", "PageSEO")
    route_names = [item[1] for item in PUBLIC_PAGES] + [item[1] for item in NOINDEX_PAGES]
    PageSEO.objects.filter(exact_path="", route_name__in=route_names).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("pages", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_page_seo, reverse_seed),
    ]
