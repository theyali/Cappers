from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from game.models import Prediction, PredictionCoupon

from .models import AnalystFollow, AnalystProfile, User


MARKET_LABELS = {
    "winner": "Победитель",
    "total": "Тотал",
    "handicap": "Фора",
    "both_score": "Обе забьют",
    "double_chance": "Двойной шанс",
    "first_half_winner": "1-й тайм",
    "first_half_total": "Тотал 1-го тайма",
    "team_total": "Индивидуальный тотал",
    "exact_score": "Точный счет",
}


def _initials(name: str) -> str:
    parts = [part for part in (name or "").split() if part]
    return "".join(part[0] for part in parts[:2]).upper() or "К"


@ensure_csrf_cookie
def expert_profile(request, username: str):
    profile = get_object_or_404(
        AnalystProfile.objects.select_related("user"),
        user__username=username,
        user__role=User.Role.ANALYST,
        is_public=True,
    )
    analyst = profile.user

    published = Prediction.objects.filter(
        coupon__author=analyst,
        coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
    )
    stats = published.aggregate(
        predictions=Count("id"),
        wins=Count("id", filter=Q(state_status=Prediction.StateStatus.WIN)),
        losses=Count("id", filter=Q(state_status=Prediction.StateStatus.LOSE)),
        refunds=Count("id", filter=Q(state_status=Prediction.StateStatus.REFUND)),
        open_predictions=Count("id", filter=Q(state_status="")),
        coupons=Count("coupon_id", distinct=True),
        total_stake=Sum("stake"),
        avg_coefficient=Avg("coefficient"),
    )
    settled = stats["wins"] + stats["losses"]
    win_rate = round(stats["wins"] / settled * 100) if settled else 0
    followers_count = AnalystFollow.objects.filter(analyst=analyst).count()
    predictions_count = stats["predictions"] or 0

    is_following = False
    if request.user.is_authenticated and request.user.pk != analyst.pk:
        is_following = AnalystFollow.objects.filter(
            follower=request.user,
            analyst=analyst,
        ).exists()

    latest_predictions = list(
        published.select_related(
            "match__league__country",
            "match__home_team",
            "match__away_team",
        ).order_by("-coupon__published_at", "-created_at")[:12]
    )

    name = profile.display_name or analyst.get_full_name() or analyst.username
    market_distribution = _distribution_rows(
        published.values("market").annotate(total=Count("id")).order_by("-total", "market")[:8],
        predictions_count,
        label_getter=lambda row: MARKET_LABELS.get(row["market"], row["market"] or "Рынок"),
    )
    selection_distribution = _distribution_rows(
        published.values("selection").annotate(total=Count("id")).order_by("-total", "selection")[:8],
        predictions_count,
        label_getter=lambda row: row["selection"] or "Выбор",
    )
    league_distribution = _league_rows(published, predictions_count)
    status_distribution = _status_rows(stats, predictions_count)
    system_totals = {
        "experts": AnalystProfile.objects.filter(is_public=True, user__role=User.Role.ANALYST).count(),
        "predictions": Prediction.objects.filter(
            coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        ).count(),
        "coupons": PredictionCoupon.objects.filter(
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        ).count(),
    }

    return render(
        request,
        "cabinet/expert_profile.html",
        {
            "expert": analyst,
            "analyst_profile": profile,
            "expert_name": name,
            "expert_initials": _initials(name),
            "followers_count": followers_count,
            "predictions_count": predictions_count,
            "wins_count": stats["wins"],
            "losses_count": stats["losses"],
            "refunds_count": stats["refunds"],
            "open_predictions_count": stats["open_predictions"],
            "coupons_count": stats["coupons"] or 0,
            "total_stake": stats["total_stake"] or 0,
            "avg_coefficient": stats["avg_coefficient"] or 0,
            "win_rate": win_rate,
            "settled_count": settled,
            "market_distribution": market_distribution,
            "selection_distribution": selection_distribution,
            "league_distribution": league_distribution,
            "status_distribution": status_distribution,
            "system_totals": system_totals,
            "is_following": is_following,
            "is_self": request.user.is_authenticated and request.user.pk == analyst.pk,
            "latest_predictions": latest_predictions,
        },
    )


def _distribution_rows(rows, total: int, *, label_getter):
    result = []
    for row in rows:
        count = row["total"] or 0
        percent = round(count / total * 100) if total else 0
        result.append(
            {
                "label": label_getter(row),
                "count": count,
                "percent": percent,
            }
        )
    return result


def _league_rows(queryset, total: int) -> list[dict]:
    rows = (
        queryset.values("match__league__name_ru", "match__league__name")
        .annotate(
            total=Count("id"),
            wins=Count("id", filter=Q(state_status=Prediction.StateStatus.WIN)),
            losses=Count("id", filter=Q(state_status=Prediction.StateStatus.LOSE)),
        )
        .order_by("-total", "match__league__name_ru")[:8]
    )
    result = []
    for row in rows:
        count = row["total"] or 0
        settled = (row["wins"] or 0) + (row["losses"] or 0)
        result.append(
            {
                "label": row["match__league__name_ru"] or row["match__league__name"] or "Лига не указана",
                "count": count,
                "percent": round(count / total * 100) if total else 0,
                "win_rate": round((row["wins"] or 0) / settled * 100) if settled else 0,
            }
        )
    return result


def _status_rows(stats: dict, total: int) -> list[dict]:
    source = [
        ("Победы", stats["wins"] or 0, "win"),
        ("Поражения", stats["losses"] or 0, "lose"),
        ("Возвраты", stats["refunds"] or 0, "refund"),
        ("В ожидании", stats["open_predictions"] or 0, "open"),
    ]
    return [
        {
            "label": label,
            "count": count,
            "percent": round(count / total * 100) if total else 0,
            "state": state,
        }
        for label, count, state in source
    ]


@login_required
@require_POST
def toggle_follow(request, user_id: int):
    analyst = get_object_or_404(
        User,
        pk=user_id,
        role=User.Role.ANALYST,
        analyst_profile__is_public=True,
    )
    if analyst.pk == request.user.pk:
        return JsonResponse(
            {"ok": False, "error": "Нельзя подписаться на самого себя."},
            status=400,
        )

    follow, created = AnalystFollow.objects.get_or_create(
        follower=request.user,
        analyst=analyst,
    )
    active = created
    if not created:
        follow.delete()
        active = False

    return JsonResponse(
        {
            "ok": True,
            "active": active,
            "followers_count": AnalystFollow.objects.filter(analyst=analyst).count(),
            "message": "Вы подписаны." if active else "Подписка отменена.",
        }
    )
