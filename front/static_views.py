from django.shortcuts import get_object_or_404, render

from front.models import StaticPage


def static_page(request, slug: str):
    page = get_object_or_404(StaticPage, slug=slug, is_published=True)
    return render(request, "front/static_page.html", {"page": page})
