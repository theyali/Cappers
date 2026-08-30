from django.db.models import Count, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie

from front.capper_stats_service import CapperStatsService
from front.prediction_views import _decorate_predictions, _published_queryset
from game.models import PredictionCoupon

from .models import AnalystFollow, AnalystProfile, CapperMonthlyStat, User
from .sport_stats import MONTH_NAMES_RU, sport_profit_periods


RECENT_PERFORMANCE_LIMITS = (10, 100)
RECENT_PERFORMANCE_STATES = (
    PredictionCoupon.StateStatus.WIN,
    PredictionCoupon.StateStatus.LOSE,
    PredictionCoupon.StateStatus.REFUND,
)
RECOMMENDED_EXPERTS_LIMIT = 8


def _initials(value: str) -> str:
    parts = [part for part in (value or "").split() if part]
    return "".join(part[0] for part in parts[:2]).upper() or "К"


def _prediction_word(value: int) -> str:
    value = abs(int(value))
    last_two = value % 100
    last = value % 10
    if 11 <= last_two <= 14:
        return "прогнозов"
    if last == 1:
        return "прогноз"
    if 2 <= last <= 4:
        return "прогноза"
    return "прогнозов"


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


def _recommended_experts(request, current_profile: AnalystProfile) -> list[dict]:
    profiles = AnalystProfile.objects.filter(
        user__role=User.Role.ANALYST,
        is_public=True,
        is_recommended=True,
    ).exclude(pk=current_profile.pk)

    if request.user.is_authenticated:
        profiles = profiles.exclude(user_id=request.user.pk)

    profiles = list(
        profiles.select_related("user")
        .annotate(followers_count=Count("user__analyst_followers", distinct=True))
        .order_by("-followers_count", "-is_verified", "display_name", "user__username")[
            :RECOMMENDED_EXPERTS_LIMIT
        ]
    )
    if not profiles:
        return []

    analyst_ids = [profile.user_id for profile in profiles]
    stats_by_analyst = {
        row["analyst_id"]: row
        for row in CapperMonthlyStat.objects.filter(analyst_id__in=analyst_ids)
        .values("analyst_id")
        .annotate(
            predictions_count=Sum("bets_count"),
            wins_count=Sum("wins_count"),
            losses_count=Sum("losses_count"),
            refunds_count=Sum("refunds_count"),
        )
    }

    following_ids: set[int] = set()
    if request.user.is_authenticated:
        following_ids = set(
            AnalystFollow.objects.filter(
                follower=request.user,
                analyst_id__in=analyst_ids,
            ).values_list("analyst_id", flat=True)
        )

    result = []
    for profile in profiles:
        user = profile.user
        name = profile.display_name or user.get_full_name() or user.username
        avatar_url = ""
        if profile.avatar:
            avatar_url = profile.avatar.url
        elif user.avatar:
            avatar_url = user.avatar.url
        stats = stats_by_analyst.get(profile.user_id, {})
        predictions_count = int(stats.get("predictions_count") or 0)
        result.append(
            {
                "id": profile.user_id,
                "username": user.username,
                "name": name,
                "initials": _initials(name),
                "avatar_url": avatar_url,
                "is_vip": bool(profile.is_vip),
                "profile_url": reverse(
                    "front:expert_profile",
                    kwargs={"username": user.username},
                ),
                "followers_count": int(profile.followers_count or 0),
                "predictions_count": predictions_count,
                "predictions_label": _prediction_word(predictions_count),
                "wins_count": int(stats.get("wins_count") or 0),
                "losses_count": int(stats.get("losses_count") or 0),
                "refunds_count": int(stats.get("refunds_count") or 0),
                "is_following": profile.user_id in following_ids,
            }
        )
    return result


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
    context["recommended_experts"] = _recommended_experts(request, profile)

    return render(
        request,
        "cabinet/expert_profile_performance.html",
        context,
    )
