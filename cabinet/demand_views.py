from django.contrib.auth.decorators import login_required
from django.db.models import Count, Max, Q
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from game.models import Match, PredictionCoupon


@login_required
@require_GET
def prediction_demand(request):
    if not request.user.is_analyst:
        return JsonResponse(
            {"ok": False, "error": "Раздел доступен только капперам."},
            status=403,
        )

    active_sort = request.GET.get("sort", "demand")
    if active_sort not in {"demand", "time"}:
        active_sort = "demand"

    matches = (
        Match.objects.filter(
            sync_scope=Match.SyncScope.PREMATCH,
            prediction_requests__isnull=False,
        )
        .select_related(
            "league__country",
            "home_team",
            "away_team",
        )
        .annotate(
            requests_count=Count("prediction_requests", distinct=True),
            latest_request_at=Max("prediction_requests__created_at"),
            predictions_count=Count(
                "predictions__coupon",
                filter=Q(
                    predictions__coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
                    predictions__coupon__is_paid=False,
                ),
                distinct=True,
            ),
            own_predictions_count=Count(
                "predictions__coupon",
                filter=Q(
                    predictions__coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
                    predictions__coupon__author=request.user,
                ),
                distinct=True,
            ),
        )
    )

    if active_sort == "time":
        matches = matches.order_by("starts_at", "-requests_count", "id")
    else:
        matches = matches.order_by("-requests_count", "starts_at", "id")

    items = []
    total_requests = 0
    for match in matches[:100]:
        requests_count = match.requests_count or 0
        total_requests += requests_count
        items.append(
            {
                "id": match.id,
                "title": f"{match.home_team_name or 'Хозяева'} — {match.away_team_name or 'Гости'}",
                "home_team": match.home_team_name or "Хозяева",
                "away_team": match.away_team_name or "Гости",
                "home_logo": match.home_team_logo or "",
                "away_logo": match.away_team_logo or "",
                "league": match.league_name or "Лига не указана",
                "country": match.league_country or "",
                "starts_at": match.starts_at.isoformat() if match.starts_at else "",
                "requests_count": requests_count,
                "predictions_count": match.predictions_count or 0,
                "has_own_prediction": bool(match.own_predictions_count),
                "latest_request_at": (
                    match.latest_request_at.isoformat()
                    if match.latest_request_at
                    else ""
                ),
                "url": match.get_absolute_url(),
            }
        )

    return JsonResponse(
        {
            "ok": True,
            "sort": active_sort,
            "matches_count": len(items),
            "total_requests": total_requests,
            "items": items,
        }
    )
