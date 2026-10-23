from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from front.models import StaticPage
from pages.documents import build_document_context


def static_page(request, slug: str):
    document_context = build_document_context(request)
    if document_context:
        return render(request, "front/legal_document.html", document_context)
    page = get_object_or_404(StaticPage, slug=slug, is_published=True)
    # Only the view knows the page title, so it builds the trail itself.
    breadcrumbs = [{"title": "Главная", "url": reverse("front:index")}, {"title": page.title}]
    return render(request, "front/static_page.html", {"page": page, "breadcrumbs": breadcrumbs})


def rules(request):
    context = build_document_context(request)
    return render(request, "front/legal_document.html" if context else "front/rules.html", context or {})
