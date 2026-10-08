from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from front.models import StaticPage


def static_page(request, slug: str):
    page = get_object_or_404(StaticPage, slug=slug, is_published=True)
    # Only the view knows the page title, so it builds the trail itself.
    breadcrumbs = [{"title": "Главная", "url": reverse("front:index")}, {"title": page.title}]
    return render(request, "front/static_page.html", {"page": page, "breadcrumbs": breadcrumbs})
