from django.db.utils import OperationalError, ProgrammingError
from django.db.models import Prefetch
from django.urls import NoReverseMatch, reverse

from back.models import FooterButton, FooterLink, FooterLinkGroup, WebsiteSettings
from front.models import WikiVideo


def _route_url(name: str):
    try:
        return reverse(name)
    except NoReverseMatch:
        return None


def _breadcrumbs_for_request(request):
    match = request.resolver_match
    view_name = match.view_name if match else ""
    if not view_name or view_name == "front:index":
        return []

    home = {"title": "Главная", "url": _route_url("front:index")}
    items = {
        "game:match_list": [{"title": "Матчи"}],
        "front:predictions": [{"title": "Все прогнозы"}],
        "front:following_feed": [{"title": "Моя лента"}],
        "front:favorites": [{"title": "Избранное"}],
        "front:bookmakers": [{"title": "Букмекеры"}],
        "front:bonuses": [{"title": "Бонусы"}],
        "front:sports_news": [{"title": "Новости спорта"}],
        "front:articles": [{"title": "Статьи"}],
        "front:cappers_stats": [{"title": "Капперы"}],
        "front:cappers_table": [{"title": "Капперы"}],
        "front:how_it_works": [{"title": "Как пользоваться"}],
        "front:wiki": [{"title": "Wiki"}],
        "tournaments:index": [{"title": "Турниры"}],
        "cabinet:profile": [{"title": "Личный кабинет"}],
    }
    dynamic = {
        "front:article_detail": [
            {"title": "Статьи", "url": _route_url("front:articles")},
            {"title": "Материал"},
        ],
        "front:prediction_detail": [
            {"title": "Все прогнозы", "url": _route_url("front:predictions")},
            {"title": "Прогноз"},
        ],
        "front:expert_profile": [
            {"title": "Капперы", "url": _route_url("front:cappers_stats")},
            {"title": match.kwargs.get("username", "Профиль")},
        ],
        "tournaments:detail": [
            {"title": "Турниры", "url": _route_url("tournaments:index")},
            {"title": "Турнир"},
        ],
        "tournaments:predict": [
            {"title": "Турниры", "url": _route_url("tournaments:index")},
            {"title": "Прогноз"},
        ],
        "front:static_page": [{"title": "Документы"}, {"title": "Страница"}],
    }

    trail = dynamic.get(view_name) or items.get(view_name)
    if trail is None:
        return []
    return [home, *trail]


def website_settings(request):
    try:
        settings = WebsiteSettings.load()
        footer_groups = (
            FooterLinkGroup.objects.filter(is_active=True)
            .prefetch_related(
                Prefetch(
                    "links",
                    queryset=FooterLink.objects.filter(is_active=True).order_by("order", "id"),
                    to_attr="active_links",
                )
            )
            .order_by("order", "id")
        )
        footer_buttons = FooterButton.objects.filter(
            is_active=True,
        ).order_by("kind", "order", "id")
        footer_buttons_by_kind = {
            "app": [],
            "social": [],
            "partner": [],
        }
        for item in footer_buttons:
            if item.kind == "app" and not (item.url or "").strip("# "):
                continue
            footer_buttons_by_kind.setdefault(item.kind, []).append(item)
        footer_groups = [
            group for group in footer_groups if getattr(group, "active_links", None)
        ]
    except (OperationalError, ProgrammingError):
        settings = None
        footer_groups = []
        footer_buttons_by_kind = {
            "app": [],
            "social": [],
            "partner": [],
        }

    request.website_settings = settings
    view_name = request.resolver_match.view_name if request.resolver_match else ""

    home_wiki_videos = []
    if view_name == "front:index":
        try:
            home_wiki_videos = list(
                WikiVideo.objects.filter(
                    is_published=True,
                    section__is_active=True,
                )
                .select_related("section")
                .order_by("sort_order", "id")[:2]
            )
        except (OperationalError, ProgrammingError):
            home_wiki_videos = []

    return {
        "website_settings": settings,
        "footer_link_groups": footer_groups,
        "footer_buttons": footer_buttons_by_kind,
        "breadcrumbs": _breadcrumbs_for_request(request),
        "hide_footer": view_name == "front:prediction_detail",
        "home_wiki_videos": home_wiki_videos,
    }
