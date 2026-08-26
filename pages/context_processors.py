import json

from django.db.utils import OperationalError, ProgrammingError

from .models import PageSEO


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


def page_seo(request):
    resolver_match = getattr(request, "resolver_match", None)
    route_name = resolver_match.view_name if resolver_match else ""
    current_path = request.path or "/"
    page = None

    if route_name:
        try:
            page = (
                PageSEO.objects.filter(
                    route_name=route_name,
                    exact_path=current_path,
                    is_active=True,
                ).first()
                or PageSEO.objects.filter(
                    route_name=route_name,
                    exact_path="",
                    is_active=True,
                ).first()
            )
        except (OperationalError, ProgrammingError):
            page = None

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
    return {"seo_meta": seo_meta}
