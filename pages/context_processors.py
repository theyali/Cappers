import json

from django.core.cache import cache
from django.db.utils import OperationalError, ProgrammingError
from django.urls import NoReverseMatch, reverse

from cabinet.models import User
from cabinet.presence import presence_payload

from .models import PageSEO
from .promo_banners import page_promo_banner_groups


PAGE_CONTEXT_CACHE_SECONDS = 120
PAGE_CONTEXT_CACHE_VERSION_KEY = "page-seo-context-version"
ROUTE_FALLBACKS = {
    "front:prediction_detail": ("front:predictions",),
    "front:favorites": ("front:predictions",),
    "game:match_detail": ("game:match_list",),
    "game:match_list_filtered": ("game:match_list",),
    "game:match_list_live": ("game:match_list",),
}
PUBLIC_PROFILE_ROUTES = {
    "front:expert_profile",
    "cabinet:user_profile",
}


def _absolute_media_url(request, field) -> str:
    if not field:
        return ""
    try:
        return request.build_absolute_uri(field.url)
    except (ValueError, AttributeError):
        return ""


def _schema_json(page, canonical_url: str) -> str:
    if not page:
        return ""
    if page.schema_json_ld:
        return page.schema_json_ld
    if not page.schema_type:
        return ""

    payload = {
        "@context": "https://schema.org",
        "@type": page.schema_type,
        "url": canonical_url,
    }
    title = page.meta_title or page.og_title
    description = page.meta_description or page.og_description
    if title:
        payload["name"] = title
    if description:
        payload["description"] = description
    return json.dumps(payload, ensure_ascii=False)


def _route_candidates(route_name: str) -> list[str]:
    candidates = [route_name]
    for fallback in ROUTE_FALLBACKS.get(route_name, ()):
        if fallback not in candidates:
            candidates.append(fallback)
    return candidates


def _base_path(route_name: str) -> str:
    try:
        return reverse(route_name)
    except NoReverseMatch:
        return ""


def _page_candidates(route_name: str, current_path: str):
    if not route_name:
        return

    seen: set[tuple[str, str]] = set()
    for candidate in _route_candidates(route_name):
        paths = [current_path]
        if candidate != route_name:
            base_path = _base_path(candidate)
            if base_path and base_path not in paths:
                paths.append(base_path)
        if "" not in paths:
            paths.append("")

        for exact_path in paths:
            key = (candidate, exact_path)
            if key in seen:
                continue
            seen.add(key)
            yield candidate, exact_path


def _resolve_page(route_name: str, current_path: str):
    for candidate, exact_path in _page_candidates(route_name, current_path) or ():
        page = PageSEO.objects.filter(
            route_name=candidate,
            exact_path=exact_path,
            is_active=True,
        ).first()
        if page is not None:
            return page
    return None


def _resolve_ad_page(route_name: str, current_path: str, primary_page):
    if primary_page is not None and primary_page.adv_banners.exists():
        return primary_page

    for candidate, exact_path in _page_candidates(route_name, current_path) or ():
        page = (
            PageSEO.objects.filter(
                route_name=candidate,
                exact_path=exact_path,
                is_active=True,
                adv_banners__isnull=False,
            )
            .distinct()
            .first()
        )
        if page is not None:
            return page
    return primary_page


def _page_context_cache_key(route_name: str, current_path: str) -> str:
    try:
        version = cache.get(PAGE_CONTEXT_CACHE_VERSION_KEY) or 1
    except Exception:
        version = 1
    return f"page-seo-context:v3:{version}:{route_name}:{current_path}"


def _build_page_context(route_name: str, current_path: str) -> dict:
    page = _resolve_page(route_name, current_path) if route_name else None
    adv_banners = []
    adv_placement = PageSEO.AdvPlacement.CONTENT

    if page:
        ad_page = _resolve_ad_page(route_name, current_path, page)
        if ad_page is not None:
            adv_placement = ad_page.adv_placement
            adv_banners = list(ad_page.adv_banners.all())

    promo_banner_groups = page_promo_banner_groups(
        route_name,
        current_path,
        page,
        _page_candidates,
    )
    promo_banners = promo_banner_groups["all"]

    return {
        "page": page,
        "adv_banners": adv_banners,
        "adv_placement": adv_placement,
        "promo_banners": promo_banners,
        "promo_banner_groups": promo_banner_groups,
    }


def _cached_page_context(route_name: str, current_path: str) -> dict:
    cache_key = _page_context_cache_key(route_name, current_path)
    try:
        cached = cache.get(cache_key)
    except Exception:
        cached = None
    if cached is not None:
        return cached

    context = _build_page_context(route_name, current_path)
    try:
        cache.set(cache_key, context, timeout=PAGE_CONTEXT_CACHE_SECONDS)
    except Exception:
        pass
    return context


def _public_profile_presence(resolver_match, route_name: str) -> dict:
    if route_name not in PUBLIC_PROFILE_ROUTES or resolver_match is None:
        return {}
    username = (resolver_match.kwargs or {}).get("username")
    if not username:
        return {}

    try:
        user = User.objects.filter(username=username, is_active=True).only(
            "id",
            "last_login",
        ).first()
    except (OperationalError, ProgrammingError):
        return {}

    if user is None:
        return {}
    return presence_payload(user)


def page_seo(request):
    resolver_match = getattr(request, "resolver_match", None)
    route_name = resolver_match.view_name if resolver_match else ""
    current_path = request.path or "/"

    try:
        page_context = _cached_page_context(route_name, current_path)
    except (OperationalError, ProgrammingError):
        page_context = {
            "page": None,
            "adv_banners": [],
            "adv_placement": PageSEO.AdvPlacement.CONTENT,
            "promo_banners": [],
            "promo_banner_groups": {
                "left": [],
                "center": [],
                "right": [],
                "all": [],
            },
        }

    page = page_context["page"]
    canonical_url = request.build_absolute_uri(current_path)
    if page and page.canonical_url:
        canonical_url = page.canonical_url

    seo_meta = {
        "page": page,
        "title": page.meta_title if page else "",
        "description": page.meta_description if page else "",
        "keywords": page.meta_keywords if page else "",
        "robots": page.robots if page else PageSEO.Robots.INDEX_FOLLOW,
        "canonical_url": canonical_url,
        "og_title": (page.og_title or page.meta_title) if page else "",
        "og_description": (page.og_description or page.meta_description) if page else "",
        "og_image_url": _absolute_media_url(request, page.og_image) if page else "",
        "og_type": page.og_type if page else PageSEO.OpenGraphType.WEBSITE,
        "twitter_card": page.twitter_card if page else PageSEO.TwitterCard.LARGE,
        "schema_type": page.schema_type if page else "",
        "schema_json_ld": _schema_json(page, canonical_url),
    }

    adv_placement = page_context["adv_placement"]
    if route_name in {
        "front:prediction_detail",
        "front:expert_profile",
        "cabinet:user_profile",
    }:
        adv_placement = PageSEO.AdvPlacement.SIDEBAR

    promo_banners = page_context["promo_banners"]
    promo_banner_groups = page_context.get("promo_banner_groups") or {
        "left": [],
        "center": promo_banners,
        "right": [],
        "all": promo_banners,
    }
    page_layout_columns = page.layout_columns if page else PageSEO.LayoutColumns.THREE
    return {
        "seo_meta": seo_meta,
        "adv_banners": page_context["adv_banners"],
        "adv_placement": adv_placement,
        "promo_banners": promo_banners,
        "left_promo_banners": promo_banner_groups.get("left", []),
        "center_promo_banners": promo_banner_groups.get("center", []),
        "right_promo_banners": promo_banner_groups.get("right", []),
        "promo_banner": (
            (promo_banner_groups.get("center") or promo_banners or [None])[0]
        ),
        "page_layout_columns": page_layout_columns,
        "page_layout_class": f"layout-columns-{page_layout_columns}",
        "profile_presence": _public_profile_presence(resolver_match, route_name),
    }
