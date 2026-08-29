from __future__ import annotations

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from .models import Match
from .services.match_timing import match_timing_payload


MAX_TIMING_MATCHES = 100


def _match_ids(raw_value: str) -> list[int]:
    result = []
    seen = set()
    for raw in str(raw_value or "").split(","):
        try:
            match_id = int(raw.strip())
        except (TypeError, ValueError):
            continue
        if match_id <= 0 or match_id in seen:
            continue
        seen.add(match_id)
        result.append(match_id)
        if len(result) >= MAX_TIMING_MATCHES:
            break
    return result


@require_GET
def match_timing(request):
    ids = _match_ids(request.GET.get("ids", ""))
    if not ids:
        return JsonResponse(
            {
                "ok": True,
                "timezone": timezone.get_current_timezone_name(),
                "matches": {},
            }
        )

    now = timezone.now()
    matches = Match.objects.filter(id__in=ids).only("id", "starts_at", "sync_scope")
    payload = {
        str(match.id): match_timing_payload(match, now=now)
        for match in matches
    }
    return JsonResponse(
        {
            "ok": True,
            "timezone": timezone.get_current_timezone_name(),
            "now": now.isoformat(),
            "matches": payload,
        }
    )
