from django.db.utils import OperationalError, ProgrammingError

from .models import PagePromoBanner, PageSEO, PromoBanner


PROMO_PLACEMENTS = (
    PagePromoBanner.Placement.LEFT,
    PagePromoBanner.Placement.CENTER,
    PagePromoBanner.Placement.RIGHT,
)


def _empty_groups() -> dict:
    return {placement: [] for placement in PROMO_PLACEMENTS} | {"all": []}


_VIP_CACHE_ATTR = "_promo_banner_is_vip"


def _promo_user_is_vip(user) -> bool:
    cached = getattr(user, _VIP_CACHE_ATTR, None)
    if cached is not None:
        return bool(cached)

    is_vip = bool(user.is_vip)
    try:
        setattr(user, _VIP_CACHE_ATTR, is_vip)
    except (AttributeError, TypeError):
        pass
    return is_vip


def promo_banner_matches_user(banner, user) -> bool:
    audience = banner.audience
    is_authenticated = bool(getattr(user, "is_authenticated", False))

    if audience == PromoBanner.Audience.ALL:
        return True
    if audience == PromoBanner.Audience.ANONYMOUS:
        return not is_authenticated
    if not is_authenticated:
        return False
    if audience == PromoBanner.Audience.AUTHENTICATED:
        return True

    is_capper = bool(getattr(user, "is_analyst", False))
    if audience == PromoBanner.Audience.READER:
        return bool(getattr(user, "is_reader", False))
    if audience == PromoBanner.Audience.CAPPER:
        return is_capper
    if audience == PromoBanner.Audience.VIP_CAPPER:
        return is_capper and _promo_user_is_vip(user)
    if audience == PromoBanner.Audience.NON_VIP_CAPPER:
        return is_capper and not _promo_user_is_vip(user)
    return False


def filter_promo_banner_groups(groups: dict, user) -> dict:
    filtered = _empty_groups()
    for key in (*PROMO_PLACEMENTS, "all"):
        filtered[key] = [
            banner
            for banner in groups.get(key, [])
            if promo_banner_matches_user(banner, user)
        ]
    return filtered


def _page_has_active_promos(page) -> bool:
    return (
        page.promo_banner_placements.filter(banner__is_active=True).exists()
        or page.promo_banners.filter(is_active=True).exists()
    )


def resolve_promo_page(route_name: str, current_path: str, primary_page, page_candidates):
    if primary_page is not None and _page_has_active_promos(primary_page):
        return primary_page

    for candidate, exact_path in page_candidates(route_name, current_path) or ():
        page = (
            PageSEO.objects.filter(
                route_name=candidate,
                exact_path=exact_path,
                is_active=True,
            )
            .filter(
                promo_banner_placements__banner__is_active=True,
            )
            .distinct()
            .first()
        )
        if page is not None:
            return page
        legacy_page = (
            PageSEO.objects.filter(
                route_name=candidate,
                exact_path=exact_path,
                is_active=True,
                promo_banners__isnull=False,
                promo_banners__is_active=True,
            )
            .distinct()
            .first()
        )
        if legacy_page is not None:
            return legacy_page
    return primary_page


def page_promo_banner_groups(route_name: str, current_path: str, primary_page, page_candidates):
    if not route_name:
        return _empty_groups()
    try:
        promo_page = resolve_promo_page(
            route_name,
            current_path,
            primary_page,
            page_candidates,
        )
        if promo_page is None:
            return _empty_groups()

        groups = _empty_groups()
        placements = list(
            promo_page.promo_banner_placements.filter(banner__is_active=True)
            .select_related("banner")
            .order_by("placement", "sort_order", "id")
        )
        if placements:
            for placement in placements:
                groups[placement.placement].append(placement.banner)
                groups["all"].append(placement.banner)
            return groups

        legacy_banners = list(promo_page.promo_banners.filter(is_active=True))
        groups[PagePromoBanner.Placement.CENTER] = legacy_banners
        groups["all"] = legacy_banners
        return groups
    except (OperationalError, ProgrammingError):
        return _empty_groups()


def page_promo_banners(route_name: str, current_path: str, primary_page, page_candidates):
    return page_promo_banner_groups(
        route_name,
        current_path,
        primary_page,
        page_candidates,
    )["all"]
