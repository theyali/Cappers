from types import SimpleNamespace

from django.conf import settings as django_settings
from django.core.cache import cache
from django.db.models import Count, Prefetch
from django.db.utils import OperationalError, ProgrammingError
from django.urls import NoReverseMatch, reverse

from back.models import Bookmaker, FooterButton, FooterLink, FooterLinkGroup, WebsiteSettings
from front.models import WikiVideo


GLOBAL_CONTEXT_CACHE_KEY = "website-context:v2"
GLOBAL_CONTEXT_CACHE_SECONDS = 120
BOOKMAKERS_CONTEXT_CACHE_KEY = "bookmakers-context:v1"
BOOKMAKERS_CONTEXT_CACHE_SECONDS = 120
HOME_WIKI_CACHE_KEY = "home-wiki-videos:v1"
HOME_WIKI_CACHE_SECONDS = 120
ROULETTE_SETTINGS_CACHE_KEY = "roulette-settings:v1"
ROULETTE_SETTINGS_CACHE_SECONDS = 60
FOOTER_VISIBLE_ROUTES = {
    "front:index",
    "front:wiki",
    "front:news_detail",
    "front:how_it_works",
    "front:bookmakers",
    "front:article_detail",
    "front:static_page",
    "front:about",
    "front:rules",
}
FOOTER_REQUIRED_LINKS = (
    {
        "group_title": "Сервис",
        "group_id": "service",
        "group_order": 20,
        "title": "О нас",
        "url": "/about/",
        "order": 5,
    },
    {
        "group_title": "Документы",
        "group_id": "documents",
        "group_order": 30,
        "title": "Правила",
        "url": "/rules/",
        "order": 5,
    },
)


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


def _ensure_required_footer_links(footer_groups):
    groups = list(footer_groups)
    groups_by_title = {group.title: group for group in groups}

    for link_data in FOOTER_REQUIRED_LINKS:
        group = groups_by_title.get(link_data["group_title"])
        if group is None:
            group = SimpleNamespace(
                id=f"fallback-{link_data['group_id']}",
                title=link_data["group_title"],
                order=link_data["group_order"],
                active_links=[],
            )
            groups.append(group)
            groups_by_title[group.title] = group

        links = list(getattr(group, "active_links", None) or [])
        has_link = any(getattr(item, "url", "") == link_data["url"] for item in links)
        if has_link:
            group.active_links = links
            continue

        links.append(
            SimpleNamespace(
                id=f"fallback-{link_data['group_id']}-{link_data['order']}",
                title=link_data["title"],
                url=link_data["url"],
                order=link_data["order"],
                is_active=True,
            )
        )
        links.sort(key=lambda item: (getattr(item, "order", 0), str(getattr(item, "id", ""))))
        group.active_links = links

    return [
        group
        for group in sorted(
            groups,
            key=lambda item: (getattr(item, "order", 0), str(getattr(item, "id", ""))),
        )
        if getattr(group, "active_links", None)
    ]


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
    footer_groups = _ensure_required_footer_links(footer_groups)

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


def _mobile_coupon_nav_state(request) -> dict:
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated or not getattr(user, "is_analyst", False):
        return {
            "count": 0,
            "coefficient": "0.00",
        }

    try:
        from game.models import PredictionCoupon

        coupon = (
            PredictionCoupon.objects.filter(
                author=user,
                published_status=PredictionCoupon.PublishedStatus.DRAFT,
                prediction_format=PredictionCoupon.PredictionFormat.QUICK,
            )
            .annotate(items_count=Count("predictions", distinct=True))
            .order_by("-updated_at", "-id")
            .first()
        )
    except (OperationalError, ProgrammingError):
        coupon = None

    if coupon is None:
        return {
            "count": 0,
            "coefficient": "0.00",
        }

    coefficient = "0.00"
    if coupon.total_stake and coupon.total_stake > 0 and coupon.possible_payout:
        coefficient = f"{coupon.possible_payout / coupon.total_stake:.2f}"

    return {
        "count": int(getattr(coupon, "items_count", 0) or 0),
        "coefficient": coefficient,
    }


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
        "front:cappers_table": [{"title": "Капперы"}],
        "front:how_it_works": [{"title": "Как пользоваться"}],
        "front:wiki": [{"title": "Wiki"}],
        "front:about": [{"title": "О нас"}],
        "front:rules": [{"title": "Правила"}],
        "tournaments:index": [{"title": "Турниры"}],
        "cabinet:profile": [{"title": "Личный кабинет"}],
    }
    dynamic = {
        "front:article_detail": [
            {"title": "Статьи", "url": _route_url("front:articles")},
            {"title": "Материал"},
        ],
        "front:news_detail": [
            {"title": "Новости спорта", "url": _route_url("front:sports_news")},
            {"title": "Новость"},
        ],
        "front:prediction_detail": [
            {"title": "Все прогнозы", "url": _route_url("front:predictions")},
            {"title": "Прогноз"},
        ],
        "front:expert_profile": [
            {"title": "Капперы", "url": _route_url("front:cappers_table")},
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
    }

    trail = dynamic.get(view_name) or items.get(view_name)
    if trail is None:
        return []
    return [home, *trail]


def _hide_footer_for_request(request) -> bool:
    view_name = request.resolver_match.view_name if request.resolver_match else ""
    return view_name not in FOOTER_VISIBLE_ROUTES


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

    mobile_quick_access = []
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        try:
            from cabinet.mobile_quick_access import mobile_quick_access_items

            mobile_quick_access = mobile_quick_access_items(user)
        except (OperationalError, ProgrammingError):
            mobile_quick_access = []

    mobile_coupon_nav = _mobile_coupon_nav_state(request)

    return {
        "website_settings": settings,
        "footer_link_groups": footer_groups,
        "footer_buttons": footer_buttons_by_kind,
        "bookmakers": bookmakers_context["bookmakers"],
        "home_bookmakers": bookmakers_context["home_bookmakers"],
        "breadcrumbs": _breadcrumbs_for_request(request),
        "hide_footer": _hide_footer_for_request(request),
        "home_wiki_videos": home_wiki_videos,
        "roulette_available_spins": _roulette_available_spins(request),
        "mobile_coupon_nav_count": mobile_coupon_nav["count"],
        "mobile_coupon_nav_coefficient": mobile_coupon_nav["coefficient"],
        "mobile_quick_access_items": mobile_quick_access,
        "support_email": django_settings.SUPPORT_EMAIL,
        "administrator_email": django_settings.ADMINISTRATOR_EMAIL,
    }
