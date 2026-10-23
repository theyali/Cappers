from django.urls import NoReverseMatch, reverse

from .context_processors import _resolve_page
from .models import document_ui_labels


def build_document_context(request):
    route = request.resolver_match.view_name if request.resolver_match else ""
    page = _resolve_page(route, request.path)
    if page is None or not page.document_enabled:
        return None
    sections = []
    for index, section in enumerate(page.document_sections.filter(is_active=True), start=1):
        sections.append({
            "title": section.title, "number": f"{index:02d}", "content": section.content,
            "anchor": section.anchor or f"document-section-{section.pk}", "kind": section.kind,
        })
    related = []
    for item in page.document_related_pages.filter(is_active=True, document_enabled=True).order_by("pk"):
        try:
            url = item.exact_path or reverse(item.route_name)
        except NoReverseMatch:
            continue
        related.append({"title": item.document_title or item.name, "url": url, "icon": item.document_icon})
    return {
        "document": page, "document_sections": sections,
        "document_cookies": list(page.document_cookies.all()), "document_related": related,
        "document_labels": {**document_ui_labels(), **page.document_labels},
        "breadcrumbs_inside_content": True, "page_class": "legal-document-page",
    }
