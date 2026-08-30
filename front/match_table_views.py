from django.http import JsonResponse
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET

from cabinet.models import User
from game.models import Match


MAX_TABLE_ODDS_BATCH = 24


def _match_ids(raw_value: str) -> list[int]:
    ids = []
    seen = set()
    for token in str(raw_value or "").split(","):
        token = token.strip()
        if not token.isdigit():
            continue
        value = int(token)
        if value <= 0 or value in seen:
            continue
        seen.add(value)
        ids.append(value)
        if len(ids) >= MAX_TABLE_ODDS_BATCH:
            break
    return ids


@require_GET
def match_table_odds(request):
    ids = _match_ids(request.GET.get("ids", ""))
    if not ids:
        return JsonResponse({"ok": True, "items": {}})

    can_write_coupon = (
        request.user.is_authenticated
        and request.user.role == User.Role.ANALYST
    )
    matches = {
        match.pk: match
        for match in Match.objects.filter(pk__in=ids).select_related(
            "sport",
            "league__country",
            "home_team",
            "away_team",
            "odds",
        )
    }

    items = {}
    for match_id in ids:
        match = matches.get(match_id)
        if match is None:
            continue
        items[str(match_id)] = render_to_string(
            "game/includes/_match_table_odds_buttons.html",
            {
                "match": match,
                "can_write_coupon": can_write_coupon,
            },
            request=request,
        )

    return JsonResponse({"ok": True, "items": items})
