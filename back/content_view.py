from collections import OrderedDict

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods


CONTENT_VIEW_SESSION_KEY = "ui.content_view_mode"
CONTENT_VIEW_MODES = {"grid", "table"}
DEFAULT_CONTENT_VIEW_MODE = "grid"


def content_view_mode(request, *, requested=None):
    """Resolve the shared grid/table mode without duplicating page-specific logic."""
    candidate = requested or request.GET.get("view_mode")
    if candidate in CONTENT_VIEW_MODES:
        return candidate

    saved = request.session.get(CONTENT_VIEW_SESSION_KEY)
    if saved in CONTENT_VIEW_MODES:
        return saved
    return DEFAULT_CONTENT_VIEW_MODE


def is_content_view_fragment(request):
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        and request.GET.get("view_fragment") == "1"
    )


@require_http_methods(["GET", "POST"])
def content_view_state(request):
    source = request.POST if request.method == "POST" else request.GET
    mode = source.get("mode", "").strip().lower()
    if mode not in CONTENT_VIEW_MODES:
        return JsonResponse({"ok": False, "error": "invalid_view_mode"}, status=400)

    request.session[CONTENT_VIEW_SESSION_KEY] = mode
    request.session.modified = True
    return JsonResponse({"ok": True, "mode": mode})


def group_by_sport_and_league(items):
    """Group matches or prediction cards by sport -> league while preserving source order."""
    sports = OrderedDict()

    for item in items:
        match = getattr(item, "match", item)
        sport = getattr(match, "sport", None)
        sport_code = getattr(sport, "code", "") or "other"
        sport_name = (
            getattr(sport, "name_ru", "")
            or getattr(sport, "name", "")
            or "Другой спорт"
        )
        sport_key = (getattr(sport, "pk", None), sport_code)

        if sport_key not in sports:
            sports[sport_key] = {
                "code": sport_code,
                "name": sport_name,
                "count": 0,
                "leagues": OrderedDict(),
            }

        sport_group = sports[sport_key]
        sport_group["count"] += 1

        league = getattr(match, "league", None)
        league_id = getattr(match, "league_id", None)
        league_name = (
            getattr(match, "league_name", "")
            or getattr(league, "name_ru", "")
            or getattr(league, "name", "")
            or "Лига не указана"
        )
        league_country = (
            getattr(match, "league_country", "")
            or getattr(getattr(league, "country", None), "name_ru", "")
            or getattr(getattr(league, "country", None), "name", "")
            or ""
        )
        league_logo = getattr(league, "logo", "") or ""
        league_key = (league_id, league_name)

        if league_key not in sport_group["leagues"]:
            sport_group["leagues"][league_key] = {
                "id": league_id,
                "name": league_name,
                "country": league_country,
                "logo": league_logo,
                "count": 0,
                "items": [],
            }

        league_group = sport_group["leagues"][league_key]
        league_group["count"] += 1
        league_group["items"].append(item)

    result = []
    for sport_group in sports.values():
        sport_group["leagues"] = list(sport_group["leagues"].values())
        result.append(sport_group)
    return result
