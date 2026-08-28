from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from cabinet.models import MatchPredictionRequest

from .models import Match


@require_GET
def prediction_request_state(request, match_id: int):
    match = get_object_or_404(Match, pk=match_id)
    requests = MatchPredictionRequest.objects.filter(match=match)
    is_active = False
    if request.user.is_authenticated:
        is_active = requests.filter(user=request.user).exists()

    return JsonResponse(
        {
            "ok": True,
            "match_id": match.id,
            "available": match.sync_scope == Match.SyncScope.PREMATCH,
            "authenticated": request.user.is_authenticated,
            "active": is_active,
            "requests_count": requests.count(),
        }
    )


@login_required
@require_POST
def toggle_prediction_request(request, match_id: int):
    match = get_object_or_404(Match, pk=match_id)
    if match.sync_scope != Match.SyncScope.PREMATCH:
        return JsonResponse(
            {
                "ok": False,
                "error": "Запрос прогноза доступен только до начала матча.",
            },
            status=409,
        )

    prediction_request, created = MatchPredictionRequest.objects.get_or_create(
        user=request.user,
        match=match,
    )
    active = created
    if not created:
        prediction_request.delete()
        active = False

    return JsonResponse(
        {
            "ok": True,
            "active": active,
            "requests_count": MatchPredictionRequest.objects.filter(match=match).count(),
            "message": (
                "Запрос прогноза добавлен."
                if active
                else "Запрос прогноза отменён."
            ),
        }
    )
