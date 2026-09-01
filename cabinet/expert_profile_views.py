from django.db.models import Count, Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie

from front.capper_stats_service import CapperStatsService
from front.prediction_views import _decorate_predictions, _published_queryset
from game.models import PredictionCoupon
from tournaments.models import Tournament, TournamentParticipant, TournamentResult
from tournaments.services.leaderboard import tournament_leaderboard

from .achievements import (
    _best_win_streak,
    _published_predictions_count,
    _user_activity_metrics,
    build_achievement_badges,
)
from .models import AnalystFollow, AnalystProfile, CapperMonthlyStat, User
from .paid_predictions import active_paid_subscriptions_by_analyst
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


def _recommended_experts(
    request,
    current_profile: AnalystProfile | None = None,
) -> list[dict]:
    profiles = AnalystProfile.objects.filter(
        user__role=User.Role.ANALYST,
        is_public=True,
        is_recommended=True,
    )
    if current_profile is not None:
        profiles = profiles.exclude(pk=current_profile.pk)

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


def _expert_achievement_badges(profile: AnalystProfile, context: dict) -> list[dict]:
    activity = _user_activity_metrics(profile.user)
    badges = build_achievement_badges(
        predictions_count=_published_predictions_count(profile.user),
        wins_count=context.get("wins_count", 0),
        overall_roi=context.get("overall_roi", 0),
        followers_count=context.get("followers_count", 0),
        best_win_streak=_best_win_streak(profile.user),
        is_verified=profile.is_verified,
        likes_given=activity["likes_given"],
        favorites_saved=activity["favorites_saved"],
        referrals=activity["referrals"],
    )
    return list(reversed(badges))


def _participant_leaderboard_row(participant: TournamentParticipant) -> dict | None:
    for row in tournament_leaderboard(participant.tournament):
        if row["participant"].pk == participant.pk:
            return row
    return None


def _expert_tournament_rows(user: User) -> tuple[list[dict], list[dict]]:
    participations = list(
        TournamentParticipant.objects.filter(
            user=user,
            tournament__status__in=(Tournament.Status.PUBLISHED, Tournament.Status.ARCHIVED),
        )
        .select_related("tournament")
        .order_by("-tournament__ends_at", "-joined_at", "-id")
    )
    if not participations:
        return [], []

    results_by_participant = {
        result.participant_id: result
        for result in TournamentResult.objects.filter(participant__in=participations)
        .select_related("achievement", "tournament")
        .order_by("-finalized_at", "-id")
    }

    rows = []
    for participant in participations:
        tournament = participant.tournament
        runtime_status = tournament.runtime_status
        is_finished = runtime_status == "finished" or tournament.status == Tournament.Status.ARCHIVED
        result = results_by_participant.get(participant.pk)
        leaderboard_row = None
        if result is None and runtime_status in {"live", "finished"}:
            leaderboard_row = _participant_leaderboard_row(participant)

        if participant.status == TournamentParticipant.Status.DISQUALIFIED:
            status_key = "disqualified"
            status_label = "Дисквалифицирован"
        elif participant.status == TournamentParticipant.Status.LEFT:
            status_key = "left"
            status_label = "Вышел из турнира"
        elif is_finished:
            status_key = "finished"
            status_label = "Завершён"
        elif runtime_status == "live":
            status_key = "live"
            status_label = "Участвует сейчас"
        else:
            status_key = "upcoming"
            status_label = "Ожидает старта"

        source = result or leaderboard_row
        rank = getattr(source, "rank", None) if result is not None else (source or {}).get("rank")
        coupons_count = getattr(source, "coupons_count", 0) if result is not None else (source or {}).get("coupons_count", 0)
        wins_count = getattr(source, "wins_count", 0) if result is not None else (source or {}).get("wins_count", 0)
        losses_count = getattr(source, "losses_count", 0) if result is not None else (source or {}).get("losses_count", 0)
        refunds_count = getattr(source, "refunds_count", 0) if result is not None else (source or {}).get("refunds_count", 0)
        profit = getattr(source, "profit", 0) if result is not None else (source or {}).get("profit", 0)
        roi_percent = getattr(source, "roi_percent", 0) if result is not None else (source or {}).get("roi_percent", 0)

        rows.append(
            {
                "participant": participant,
                "tournament": tournament,
                "url": tournament.get_absolute_url(),
                "runtime_status": runtime_status,
                "status_key": status_key,
                "status_label": status_label,
                "is_finished": is_finished,
                "rank": rank,
                "coupons_count": coupons_count,
                "wins_count": wins_count,
                "losses_count": losses_count,
                "refunds_count": refunds_count,
                "profit": profit,
                "roi_percent": roi_percent,
                "prize_amount": result.prize_amount if result is not None else 0,
                "achievement": result.achievement if result is not None else None,
                "finalized_at": result.finalized_at if result is not None else None,
            }
        )

    current_rows = [row for row in rows if not row["is_finished"]]
    finished_rows = [row for row in rows if row["is_finished"]]
    return current_rows, finished_rows


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

    context["expert_achievement_badges"] = _expert_achievement_badges(profile, context)
    current_tournaments, finished_tournaments = _expert_tournament_rows(profile.user)
    context["expert_current_tournaments"] = current_tournaments
    context["expert_finished_tournaments"] = finished_tournaments
    context["expert_tournament_achievements"] = [
        row for row in finished_tournaments if row["achievement"] is not None
    ]
    context["expert_tournaments_count"] = len(current_tournaments) + len(finished_tournaments)

    paid_subscription = active_paid_subscriptions_by_analyst(
        request.user,
        {profile.user_id},
    ).get(profile.user_id)
    context["paid_subscription"] = paid_subscription
    context["paid_predictions_enabled"] = bool(
        profile.paid_predictions_enabled and profile.paid_predictions_price > 0
    )
    context["paid_predictions_locked"] = context["paid_predictions_enabled"]
    if context["paid_predictions_enabled"]:
        context["latest_predictions"] = []
    else:
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
