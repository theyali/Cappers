from django.core.cache import cache
from django.db.models import Prefetch
from django.db.utils import OperationalError, ProgrammingError
from django.urls import NoReverseMatch, reverse

from back.models import Bookmaker, FooterButton, FooterLink, FooterLinkGroup, WebsiteSettings
from front.models import WikiVideo


GLOBAL_CONTEXT_CACHE_KEY = "website-context:v1"
GLOBAL_CONTEXT_CACHE_SECONDS = 120
BOOKMAKERS_CONTEXT_CACHE_KEY = "bookmakers-context:v1"
BOOKMAKERS_CONTEXT_CACHE_SECONDS = 120
HOME_WIKI_CACHE_KEY = "home-wiki-videos:v1"
HOME_WIKI_CACHE_SECONDS = 120
ROULETTE_SETTINGS_CACHE_KEY = "roulette-settings:v1"
ROULETTE_SETTINGS_CACHE_SECONDS = 60


def _route_url(name: str):
    try:
        return reverse(name)
    except NoReverseMatch:
        return None


def _cache_get(key: str):
    try:
        return cache.get(key)
    except Exception:
        return None


def _cache_set(key: str, value, timeout: int) -> None:
    try:
        cache.set(key, value, timeout=timeout)
    except Exception:
        pass


def _load_global_context() -> dict:
    cached = _cache_get(GLOBAL_CONTEXT_CACHE_KEY)
    if cached is not None:
        return cached

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

    payload = {
        "settings": settings,
        "footer_groups": footer_groups,
        "footer_buttons": footer_buttons_by_kind,
    }
    _cache_set(
        GLOBAL_CONTEXT_CACHE_KEY,
        payload,
        GLOBAL_CONTEXT_CACHE_SECONDS,
    )
    return payload


def _load_bookmakers_context() -> dict:
    cached = _cache_get(BOOKMAKERS_CONTEXT_CACHE_KEY)
    if cached is not None:
        return cached

    bookmakers = list(Bookmaker.objects.all())
    home_bookmakers = [
        bookmaker for bookmaker in sorted(
            bookmakers,
            key=lambda item: (item.home_order, item.id),
        )
        if bookmaker.show_on_home
    ][:3]
    payload = {
        "bookmakers": bookmakers,
        "home_bookmakers": home_bookmakers,
    }
    _cache_set(
        BOOKMAKERS_CONTEXT_CACHE_KEY,
        payload,
        BOOKMAKERS_CONTEXT_CACHE_SECONDS,
    )
    return payload


def _home_wiki_videos() -> list:
    cached = _cache_get(HOME_WIKI_CACHE_KEY)
    if cached is not None:
        return cached

    videos = list(
        WikiVideo.objects.filter(
            is_published=True,
            section__is_active=True,
        )
        .select_related("section")
        .order_by("sort_order", "id")[:2]
    )
    _cache_set(HOME_WIKI_CACHE_KEY, videos, HOME_WIKI_CACHE_SECONDS)
    return videos


def _roulette_settings():
    cached = _cache_get(ROULETTE_SETTINGS_CACHE_KEY)
    if cached is not None:
        return cached

    from cabinet.roulette.models import RouletteSettings

    roulette_settings = RouletteSettings.objects.filter(pk=1).first()
    if roulette_settings is None:
        roulette_settings = RouletteSettings.load()
    _cache_set(
        ROULETTE_SETTINGS_CACHE_KEY,
        roulette_settings,
        ROULETTE_SETTINGS_CACHE_SECONDS,
    )
    return roulette_settings


def _roulette_available_spins(request) -> int:
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return 0

    try:
        from cabinet.roulette.state import UserRouletteState, roulette_daily_window

        roulette_settings = _roulette_settings()
        if not roulette_settings.is_enabled:
            return 0

        state = UserRouletteState.objects.filter(user_id=user.pk).only(
            "available_spins",
            "last_daily_grant_at",
        ).first()
        available_spins = int(state.available_spins) if state is not None else 0
        window_start, _ = roulette_daily_window(roulette_settings)

        daily_grant_due = (
            int(roulette_settings.daily_free_spins or 0) > 0
            and (
                state is None
                or state.last_daily_grant_at is None
                or state.last_daily_grant_at < window_start
            )
        )
        if daily_grant_due:
            available_spins += int(roulette_settings.daily_free_spins)

        return max(0, available_spins)
    except (OperationalError, ProgrammingError):
        # Keep global pages available during deploys before roulette migrations finish.
        return 0


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
        global_context = _load_global_context()
        settings = global_context["settings"]
        footer_groups = global_context["footer_groups"]
        footer_buttons_by_kind = global_context["footer_buttons"]
        bookmakers_context = _load_bookmakers_context()
    except (OperationalError, ProgrammingError):
        settings = None
        footer_groups = []
        footer_buttons_by_kind = {
            "app": [],
            "social": [],
            "partner": [],
        }
        bookmakers_context = {
            "bookmakers": [],
            "home_bookmakers": [],
        }

    request.website_settings = settings
    view_name = request.resolver_match.view_name if request.resolver_match else ""

    home_wiki_videos = []
    if view_name == "front:index":
        try:
            home_wiki_videos = _home_wiki_videos()
        except (OperationalError, ProgrammingError):
            home_wiki_videos = []

    return {
        "website_settings": settings,
        "footer_link_groups": footer_groups,
        "footer_buttons": footer_buttons_by_kind,
        "bookmakers": bookmakers_context["bookmakers"],
        "home_bookmakers": bookmakers_context["home_bookmakers"],
        "breadcrumbs": _breadcrumbs_for_request(request),
        "hide_footer": view_name == "front:prediction_detail",
        "home_wiki_videos": home_wiki_videos,
        "roulette_available_spins": _roulette_available_spins(request),
    }
