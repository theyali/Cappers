"""Небольшие AJAX endpoints фронтенда."""
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .search import build_search_context


@require_GET
def search_suggestions(request):
    data = build_search_context(request.GET.get("q", ""), preview=True)
    return JsonResponse({
        "query": data["query"],
        "total": data["total"],
        "groups": {key: data["groups"][key] for key in ("matches", "cappers", "tournaments")},
    })
