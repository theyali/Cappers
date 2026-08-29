from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import ensure_csrf_cookie

from front.capper_stats_service import CapperStatsService
from front.prediction_views import _decorate_predictions, _published_queryset
from game.models import PredictionCoupon

from .models import AnalystProfile, CapperMonthlyStat, User
from .sport_stats import MONTH_NAMES_RU, sport_profit_periods


RECENT_PERFORMANCE_LIMITS = (10, 100)
RECENT_PERFORMANCE_STATES = (
    PredictionCoupon.StateStatus.WIN,
    PredictionCoupon.StateStatus.LOSE,
    PredictionCoupon.StateStatus.REFUND,
)


def _recent_performance(author, limit: int) -> dict:
    states = list(
        PredictionCoupon.objects.filter(
            author=author,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status__in=RECENT_PERFORMANCE_STATES,
        )
        .annotate(
            result_at=Coalesce(
                "settled_at",
                "updated_at",
                "published_at",
                "created_at",
            )
        )
        .order_by("-result_at", "-id")
        .values_list("state_status", flat=True)[:limit]
    )
    total = len(states)

    def bucket(state: str) -> dict:
        count = states.count(state)
        percent = round(count / total * 100) if total else 0
        return {"count": count, "percent": percent}

    return {
        "limit": limit,
        "total": total,
        "wins": bucket(PredictionCoupon.StateStatus.WIN),
        "losses": bucket(PredictionCoupon.StateStatus.LOSE),
        "refunds": bucket(PredictionCoupon.StateStatus.REFUND),
    }


def _monthly_stats(rows: list[CapperMonthlyStat]) -> list[dict]:
    return [
        {
            "month": row.month,
            "month_label": f"{MONTH_NAMES_RU[row.month.month]} {row.month.year}",
            "bets_count": row.bets_count,
            "wins_count": row.wins_count,
            "losses_count": row.losses_count,
            "refunds_count": row.refunds_count,
            "flat_profit": row.flat_profit_percent,
            "roi": row.roi,
            "avg_coefficient": row.avg_coefficient,
            "hit_rate": row.hit_rate,
            "total_stake": row.total_stake,
            "total_profit": row.total_profit,
        }
        for row in rows
    ]


@ensure_csrf_cookie
def expert_profile(request, username: str):
    profile = get_object_or_404(
        AnalystProfile.objects.select_related("user"),
        user__username=username,
        user__role=User.Role.ANALYST,
        is_public=True,
    )
    service = CapperStatsService(request.user)
    context = service.build_expert_profile_context(profile)

    performance_windows = {
        str(limit): _recent_performance(profile.user, limit)
        for limit in RECENT_PERFORMANCE_LIMITS
    }
    context["performance_windows"] = performance_windows
    context["performance_default"] = performance_windows["10"]

    monthly_rows = list(
        CapperMonthlyStat.objects.filter(analyst=profile.user).order_by("-month", "-id")
    )
    context["monthly_stats"] = _monthly_stats(monthly_rows)
    sport_periods, sport_period_options = sport_profit_periods(monthly_rows)
    context["sport_profit_periods"] = sport_periods
    context["sport_profit_period_options"] = sport_period_options
    context["sport_profit_default"] = sport_periods["all"]

    latest_coupons = (
        _published_queryset()
        .filter(author=profile.user)
        .order_by("-published_at", "-created_at", "-id")[:12]
    )
    context["latest_predictions"] = _decorate_predictions(request, latest_coupons)

    return render(
        request,
        "cabinet/expert_profile_performance.html",
        context,
    )
