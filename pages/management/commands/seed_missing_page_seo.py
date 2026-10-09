from __future__ import annotations

from dataclasses import dataclass

from django.core.management.base import BaseCommand
from django.urls import URLPattern, URLResolver, get_resolver

from pages.models import PageSEO


@dataclass(frozen=True)
class PageSeed:
    name: str
    meta_title: str = ""
    meta_description: str = ""
    robots: str = PageSEO.Robots.NOINDEX_FOLLOW
    adv_placement: str = PageSEO.AdvPlacement.CONTENT
    layout_columns: str = PageSEO.LayoutColumns.THREE
    schema_type: str = "WebPage"


PUBLIC_PAGE_SEEDS = {
    "front:index": PageSeed(
        "Главная",
        "КапперХаб - спортивная аналитика, прогнозы и эксперты",
        "Матчи, прогнозы, спортивная аналитика, рейтинги капперов и статьи на одной платформе.",
        PageSEO.Robots.INDEX_FOLLOW,
    ),
    "front:predictions": PageSeed(
        "Все прогнозы",
        "Спортивные прогнозы и аналитика - КапперХаб",
        "Лента опубликованных спортивных прогнозов и аналитических материалов.",
        PageSEO.Robots.INDEX_FOLLOW,
    ),
    "front:predictions_rich": PageSeed(
        "Текстовые прогнозы",
        "Текстовые спортивные прогнозы - КапперХаб",
        "Текстовые прогнозы капперов с аналитикой и деталями ставок.",
        PageSEO.Robots.INDEX_FOLLOW,
    ),
    "front:prediction_expresses": PageSeed(
        "Экспрессы",
        "Экспрессы на спорт - КапперХаб",
        "Спортивные экспрессы и подборки прогнозов от капперов.",
        PageSEO.Robots.INDEX_FOLLOW,
    ),
    "front:prediction_expresses_rich": PageSeed(
        "Текстовые экспрессы",
        "Текстовые экспрессы на спорт - КапперХаб",
        "Текстовые экспрессы и аналитические подборки прогнозов.",
        PageSEO.Robots.INDEX_FOLLOW,
    ),
    "front:predictions_by_sport": PageSeed(
        "Прогнозы по виду спорта",
        "",
        "",
        PageSEO.Robots.INDEX_FOLLOW,
    ),
    "front:predictions_rich_by_sport": PageSeed(
        "Текстовые прогнозы по виду спорта",
        "",
        "",
        PageSEO.Robots.INDEX_FOLLOW,
    ),
    "front:prediction_detail": PageSeed(
        "Страница прогноза",
        "",
        "",
        PageSEO.Robots.INDEX_FOLLOW,
        PageSEO.AdvPlacement.SIDEBAR,
    ),
    "front:bookmakers": PageSeed(
        "Букмекеры",
        "Букмекеры - КапперХаб",
        "Каталог букмекерских предложений и полезной информации для пользователей КапперХаб.",
        PageSEO.Robots.INDEX_FOLLOW,
    ),
    "front:bonuses": PageSeed(
        "Бонусы букмекеров",
        "Бонусы букмекеров - КапперХаб",
        "Бонусные предложения букмекерских компаний и промоакции.",
        PageSEO.Robots.INDEX_FOLLOW,
    ),
    "front:sports_news": PageSeed(
        "Новости спорта",
        "Новости спорта - КапперХаб",
        "Новости спорта, события матчей и актуальные материалы редакции.",
        PageSEO.Robots.INDEX_FOLLOW,
    ),
    "front:news_detail": PageSeed(
        "Новость спорта",
        "",
        "",
        PageSEO.Robots.INDEX_FOLLOW,
        schema_type="Article",
    ),
    "front:articles": PageSeed(
        "Статьи",
        "Статьи о спорте и аналитике - КапперХаб",
        "Статьи, разборы матчей и материалы о спортивной аналитике.",
        PageSEO.Robots.INDEX_FOLLOW,
    ),
    "front:article_detail": PageSeed(
        "Статья",
        "",
        "",
        PageSEO.Robots.INDEX_FOLLOW,
        schema_type="Article",
    ),
    "front:capper_article_detail": PageSeed(
        "Статья каппера",
        "",
        "",
        PageSEO.Robots.INDEX_FOLLOW,
        schema_type="Article",
    ),
    "front:expert_profile": PageSeed(
        "Публичный профиль каппера",
        "",
        "",
        PageSEO.Robots.INDEX_FOLLOW,
        PageSEO.AdvPlacement.SIDEBAR,
        schema_type="ProfilePage",
    ),
    "cabinet:user_profile": PageSeed(
        "Публичный профиль пользователя",
        "",
        "",
        PageSEO.Robots.INDEX_FOLLOW,
        PageSEO.AdvPlacement.SIDEBAR,
        schema_type="ProfilePage",
    ),
    "front:cappers_table": PageSeed(
        "Капперы",
        "Рейтинг капперов - КапперХаб",
        "Рейтинг капперов, статистика экспертов и фильтры по спортивным прогнозам.",
        PageSEO.Robots.INDEX_FOLLOW,
    ),
    "front:cappers_table_group": PageSeed("Капперы по группе", "", "", PageSEO.Robots.INDEX_FOLLOW),
    "front:cappers_table_period": PageSeed("Капперы по периоду", "", "", PageSEO.Robots.INDEX_FOLLOW),
    "front:cappers_table_sport": PageSeed("Капперы по спорту", "", "", PageSEO.Robots.INDEX_FOLLOW),
    "front:how_it_works": PageSeed(
        "Как пользоваться",
        "Как пользоваться КапперХаб",
        "Инструкция по разделам, прогнозам, профилям капперов и возможностям платформы.",
        PageSEO.Robots.INDEX_FOLLOW,
    ),
    "front:wiki": PageSeed(
        "Wiki",
        "Wiki - КапперХаб",
        "Справочник терминов, видео и материалов о спортивной аналитике.",
        PageSEO.Robots.INDEX_FOLLOW,
    ),
    "front:about": PageSeed(
        "О нас",
        "О нас — КапперХаб",
        "КапперХаб собирает матчи, прогнозы и статистику капперов с открытой историей результатов.",
        PageSEO.Robots.INDEX_FOLLOW,
        PageSEO.AdvPlacement.SIDEBAR,
        schema_type="AboutPage",
    ),
    "front:rules": PageSeed(
        "Правила",
        "Правила КапперХаб",
        "Правила использования платформы КапперХаб.",
        PageSEO.Robots.INDEX_FOLLOW,
        PageSEO.AdvPlacement.SIDEBAR,
    ),
    "front:static_page": PageSeed(
        "Статическая страница", "", "", PageSEO.Robots.INDEX_FOLLOW, PageSEO.AdvPlacement.SIDEBAR
    ),
    "game:match_list": PageSeed(
        "Матчи",
        "Спортивные матчи - КапперХаб",
        "Список спортивных матчей со статусами, временем начала и основной информацией.",
        PageSEO.Robots.INDEX_FOLLOW,
    ),
    "game:match_list_live": PageSeed("Live-матчи", "", "", PageSEO.Robots.INDEX_FOLLOW),
    "game:match_list_filtered": PageSeed("Матчи по фильтру", "", "", PageSEO.Robots.INDEX_FOLLOW),
    "game:match_detail": PageSeed("Страница матча", "", "", PageSEO.Robots.INDEX_FOLLOW, schema_type="SportsEvent"),
    "game:match_predictions": PageSeed("Прогнозы на матч", "", "", PageSEO.Robots.INDEX_FOLLOW),
    "tournaments:index": PageSeed(
        "Турниры",
        "Турниры прогнозистов - КапперХаб",
        "Турниры, соревнования капперов и таблицы участников.",
        PageSEO.Robots.INDEX_FOLLOW,
    ),
    "tournaments:detail": PageSeed("Страница турнира", "", "", PageSEO.Robots.INDEX_FOLLOW),
    "tournaments:predict": PageSeed("Прогноз на турнир", "", "", PageSEO.Robots.NOINDEX_FOLLOW),
}

PRIVATE_PAGE_SEEDS = {
    "front:following_feed": PageSeed("Моя лента"),
    "front:favorites": PageSeed("Избранные прогнозы"),
    "notifications:center": PageSeed("Уведомления"),
    "cabinet:dashboard": PageSeed("Кабинет"),
    "cabinet:reader_dashboard": PageSeed("Кабинет читателя"),
    "cabinet:analyst_dashboard": PageSeed("Кабинет каппера"),
    "cabinet:profile": PageSeed("Личный кабинет"),
    "cabinet:coin_operations": PageSeed("Операции с коинами"),
    "cabinet:real_operations": PageSeed("Реальные операции"),
    "cabinet:capper_articles": PageSeed("Мои статьи"),
    "cabinet:capper_article_create": PageSeed("Новая статья"),
    "cabinet:capper_article_edit": PageSeed("Редактирование статьи"),
    "cabinet:vip_plans": PageSeed("VIP"),
    "cabinet:bonuses": PageSeed("Бонусный центр"),
    "cabinet:bonus_tasks": PageSeed("Ежедневные задания"),
    "cabinet:bonus_levels": PageSeed("Уровни"),
    "cabinet:referrals": PageSeed("Рефералы"),
    "cabinet:prediction_demand": PageSeed("Запросы прогнозов"),
    "cabinet:profile_edit": PageSeed("Редактирование профиля"),
    "cabinet:become_capper": PageSeed("Стать каппером"),
    "cabinet:become_capper_start": PageSeed("Старт регистрации каппера"),
    "cabinet:capper_onboarding": PageSeed("Онбординг каппера"),
    "cabinet:login": PageSeed("Вход"),
    "cabinet:register": PageSeed("Регистрация"),
    "cabinet:register_done": PageSeed("Регистрация завершена"),
    "cabinet:password_reset": PageSeed("Восстановление пароля"),
    "cabinet:password_reset_done": PageSeed("Письмо восстановления отправлено"),
    "cabinet:password_reset_confirm": PageSeed("Установка нового пароля"),
    "cabinet:password_reset_set": PageSeed("Новый пароль"),
    "cabinet:password_reset_complete": PageSeed("Пароль восстановлен"),
    "wallets:top_up": PageSeed("Пополнение баланса"),
    "wallets:copybetting_setup": PageSeed("Настройка копибеттинга"),
    "account_email:add": PageSeed("Добавить email"),
    "account_email:request_change": PageSeed("Смена email"),
    "account_email:confirm_change": PageSeed("Подтверждение смены email"),
    "account_email:verify": PageSeed("Подтверждение email"),
    "account_email:verify_registration_email": PageSeed("Подтверждение регистрации"),
    "bots:manage_accounts": PageSeed("Боты"),
}

ACTION_ROUTES = {
    "healthcheck",
    "robots_txt",
    "sitemap",
    "front:content_view_state",
    "front:match_table_odds",
    "front:capper_referral_code",
    "front:capper_referral",
    "front:prediction_filter_state",
    "front:prediction_comments",
    "front:prediction_like",
    "front:prediction_favorite",
    "front:prediction_share",
    "front:comment_delete",
    "front:comment_reaction",
    "front:comment_replies",
    "game:create_coupon",
    "game:rich_prediction_create",
    "game:rich_prediction_edit",
    "game:match_timing",
    "game:prediction_request_state",
    "game:toggle_prediction_request",
    "tournaments:match_odds",
    "tournaments:join",
    "tournaments:create_coupon",
    "cabinet:capper_article_submit",
    "cabinet:profile_promo_banner",
    "cabinet:vip_purchase",
    "cabinet:daily_task_claim",
    "cabinet:daily_tasks_claim_all",
    "cabinet:roulette_state",
    "cabinet:roulette_spin",
    "cabinet:request_verification",
    "cabinet:delete_account",
    "cabinet:profile_earnings",
    "cabinet:achievement_stats",
    "cabinet:following_summary",
    "cabinet:referral_stats",
    "cabinet:avatar_upload",
    "cabinet:follow_analyst",
    "cabinet:paid_predictions_subscribe",
    "cabinet:paid_predictions_decline",
    "cabinet:toggle_follow",
    "cabinet:league_search",
    "cabinet:telegram_login",
    "cabinet:telegram_webapp_login",
    "cabinet:logout",
    "cabinet:password_reset_confirm_invisible_suffix",
    "wallets:real_action",
    "wallets:copybetting_pause",
    "wallets:copybetting_resume",
    "wallets:copybetting_stop",
    "notifications:summary",
    "notifications:preferences",
    "notifications:telegram_connect",
    "notifications:telegram_disconnect",
    "notifications:mark_all_read",
    "notifications:mark_read",
    "notifications:match_watch",
    "notifications:match_watch_by_slug",
    "pages:help_content",
    "back:ajax_health",
    "bots:upload_avatar",
}

ROUTE_SEEDS = {
    **PUBLIC_PAGE_SEEDS,
    **PRIVATE_PAGE_SEEDS,
}


def iter_named_routes(resolver=None, namespaces=()):
    resolver = resolver or get_resolver()
    for pattern in resolver.url_patterns:
        if isinstance(pattern, URLResolver):
            namespace = pattern.namespace
            next_namespaces = namespaces + ((namespace,) if namespace else ())
            yield from iter_named_routes(pattern, next_namespaces)
            continue

        if not isinstance(pattern, URLPattern) or not pattern.name:
            continue

        route_name = ":".join((*namespaces, pattern.name))
        if route_name:
            yield route_name


def humanize_route_name(route_name: str) -> str:
    tail = route_name.rsplit(":", 1)[-1]
    return tail.replace("_", " ").strip().capitalize()


class Command(BaseCommand):
    help = "Create missing PageSEO records for named site pages."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print records that would be created without writing to the database.",
        )
        parser.add_argument(
            "--include-actions",
            action="store_true",
            help="Also create PageSEO records for action/API routes that are skipped by default.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        include_actions = options["include_actions"]
        route_names = sorted(set(iter_named_routes()))
        existing_routes = set(
            PageSEO.objects.filter(exact_path="")
            .values_list("route_name", flat=True)
        )

        created_count = 0
        skipped_existing = 0
        skipped_actions = 0

        for route_name in route_names:
            if route_name.startswith(("admin:", "tinymce:", "tinymce-")):
                skipped_actions += 1
                continue
            if not include_actions and route_name in ACTION_ROUTES:
                skipped_actions += 1
                continue
            if route_name in existing_routes:
                skipped_existing += 1
                continue

            seed = ROUTE_SEEDS.get(route_name) or PageSeed(humanize_route_name(route_name))
            defaults = {
                "name": seed.name,
                "meta_title": seed.meta_title,
                "meta_description": seed.meta_description,
                "robots": seed.robots,
                "adv_placement": seed.adv_placement,
                "layout_columns": seed.layout_columns,
                "schema_type": seed.schema_type,
                "is_active": True,
            }

            if dry_run:
                self.stdout.write(f"Would create: {route_name} - {seed.name}")
            else:
                PageSEO.objects.create(
                    route_name=route_name,
                    exact_path="",
                    **defaults,
                )
            created_count += 1

        verb = "Would create" if dry_run else "Created"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb}: {created_count}; existing: {skipped_existing}; skipped action/system: {skipped_actions}"
            )
        )
