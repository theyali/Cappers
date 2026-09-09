from django.db.utils import OperationalError, ProgrammingError

from .models import PageSEO


def resolve_promo_page(route_name: str, current_path: str, primary_page, page_candidates):
    if primary_page is not None and primary_page.promo_banners.filter(is_active=True).exists():
        return primary_page

    for candidate, exact_path in page_candidates(route_name, current_path) or ():
        page = (
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
        if page is not None:
            return page
    return primary_page


def page_promo_banners(route_name: str, current_path: str, primary_page, page_candidates):
    if not route_name:
        return []
    try:
        promo_page = resolve_promo_page(
            route_name,
            current_path,
            primary_page,
            page_candidates,
        )
        if promo_page is None:
            return []
        return list(promo_page.promo_banners.filter(is_active=True))
    except (OperationalError, ProgrammingError):
        return []
