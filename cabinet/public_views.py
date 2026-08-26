from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Avg, Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from game.models import Prediction, PredictionCoupon

from .models import AnalystFollow, AnalystProfile, User


MARKET_LABELS = {
    "winner": "Исход матча",
    "total": "Тотал",
    "handicap": "Фора",
    "both_score": "Обе забьют",
    "double_chance": "Двойной шанс",
    "first_half_winner": "Исход 1-го тайма",
    "first_half_total": "Тотал 1-го тайма",
    "first_half_handicap": "Фора 1-го тайма",
    "team_total": "Индивидуальный тотал",
    "exact_score": "Точный счет",
}

SETTLED_COUPON_STATES = {
    PredictionCoupon.StateStatus.WIN,
    PredictionCoupon.StateStatus.LOSE,
    PredictionCoupon.StateStatus.REFUND,
}


def _initials(name: str) -> str:
    parts = [part for part in (name or "").split() if part]
    return "".join(part[0] for part in parts[:2]).upper() or "К"


def _coupon_profit(coupon: PredictionCoupon) -> Decimal:
    stake = coupon.total_stake or Decimal("0")
    payout = coupon.possible_payout or Decimal("0")
    if coupon.state_status == PredictionCoupon.StateStatus.WIN:
        return payout - stake
    if coupon.state_status == PredictionCoupon.StateStatus.LOSE:
        return -stake
    return Decimal("0")


def _coupon_result_date(coupon: PredictionCoupon):
    return coupon.settled_at or coupon.updated_at or coupon.published_at or coupon.created_at


def _signed_money(value: Decimal) -> str:
    value = value.quantize(Decimal("0.01"))
    prefix = "+" if value > 0 else ""
    return f"{prefix}{value:.2f}"


def _roi(profit: Decimal, stake: Decimal) -> float:
    if not stake:
        return 0.0
    return round(float(profit / stake * Decimal("100")), 1)


def _profit_period(coupons: list[PredictionCoupon], *, days: int, now) -> dict:
    cutoff = now - timedelta(days=days)
    selected = [coupon for coupon in coupons if _coupon_result_date(coupon) >= cutoff]
    stake = sum((coupon.total_stake or Decimal("0") for coupon in selected), Decimal("0"))
    profit = sum((_coupon_profit(coupon) for coupon in selected), Decimal("0"))
    return {
        "days": days,
        "profit": float(profit),
        "profit_display": _signed_money(profit),
        "roi": _roi(profit, stake),
        "stake": float(stake),
        "count": len(selected),
        "positive": profit > 0,
        "negative": profit < 0,
    }


def _profit_chart(coupons: list[PredictionCoupon], *, days: int, now) -> list[dict]:
    today = timezone.localtime(now).date()
    start_date = today - timedelta(days=days - 1)
    daily_profit: dict = {}

    for coupon in coupons:
        result_date = timezone.localtime(_coupon_result_date(coupon)).date()
        if result_date < start_date or result_date > today:
            continue
        daily_profit[result_date] = daily_profit.get(result_date, Decimal("0")) + _coupon_profit(coupon)

    points = []
    balance = Decimal("0")
    for offset in range(days):
        day = start_date + timedelta(days=offset)
        balance += daily_profit.get(day, Decimal("0"))
        points.append(
            {
                "label": day.strftime("%d.%m"),
                "value": round(float(balance), 2),
            }
        )
    return points


def _current_streak(queryset) -> dict:
    states = list(
        queryset.filter(state_status__in=[Prediction.StateStatus.WIN, Prediction.StateStatus.LOSE])
        .order_by("-updated_at", "-id")
        .values_list("state_status", flat=True)[:100]
    )
    if not states:
        return {"count": 0, "label": "Нет серии", "state": "none"}

    current = states[0]
    count = 0
    for state in states:
        if state != current:
            break
        count += 1

    return {
        "count": count,
        "label": "побед подряд" if current == Prediction.StateStatus.WIN else "поражений подряд",
        "state": current,
    }


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
        avg_coefficient=Avg("coefficient"),
    )
    decided_predictions = (stats["wins"] or 0) + (stats["losses"] or 0)
    settled_predictions = decided_predictions + (stats["refunds"] or 0)
    win_rate = round((stats["wins"] or 0) / decided_predictions * 100, 1) if decided_predictions else 0
    followers_count = AnalystFollow.objects.filter(analyst=analyst).count()
    predictions_count = stats["predictions"] or 0

    published_coupons = list(
        PredictionCoupon.objects.filter(
            author=analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        ).order_by("settled_at", "updated_at", "id")
    )
    settled_coupons = [
        coupon for coupon in published_coupons if coupon.state_status in SETTLED_COUPON_STATES
    ]

    total_profit = sum((_coupon_profit(coupon) for coupon in settled_coupons), Decimal("0"))
    settled_stake = sum(
        (coupon.total_stake or Decimal("0") for coupon in settled_coupons),
        Decimal("0"),
    )
    overall_roi = _roi(total_profit, settled_stake)
    average_coupon_coefficient_values = [
        (coupon.possible_payout / coupon.total_stake)
        for coupon in published_coupons
        if coupon.total_stake and coupon.total_stake > 0 and coupon.possible_payout
    ]
    avg_coupon_coefficient = (
        sum(average_coupon_coefficient_values, Decimal("0")) / len(average_coupon_coefficient_values)
        if average_coupon_coefficient_values
        else Decimal("0")
    )

    now = timezone.now()
    profit_periods = {
        str(days): _profit_period(settled_coupons, days=days, now=now)
        for days in (7, 30, 90)
    }
    profit_chart = {
        str(days): _profit_chart(settled_coupons, days=days, now=now)
        for days in (7, 30, 90)
    }
    current_streak = _current_streak(published)

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
    market_distribution = _market_rows(published)
    league_distribution = _league_rows(published)
    status_distribution = _status_rows(stats, predictions_count)

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
            "wins_count": stats["wins"] or 0,
            "losses_count": stats["losses"] or 0,
            "refunds_count": stats["refunds"] or 0,
            "open_predictions_count": stats["open_predictions"] or 0,
            "coupons_count": stats["coupons"] or 0,
            "avg_coefficient": stats["avg_coefficient"] or 0,
            "avg_coupon_coefficient": avg_coupon_coefficient,
            "win_rate": win_rate,
            "settled_count": settled_predictions,
            "settled_coupons_count": len(settled_coupons),
            "settled_stake": settled_stake,
            "total_profit": total_profit,
            "total_profit_display": _signed_money(total_profit),
            "overall_roi": overall_roi,
            "profit_periods": profit_periods,
            "profit_chart": profit_chart,
            "current_streak": current_streak,
            "market_distribution": market_distribution,
            "league_distribution": league_distribution,
            "status_distribution": status_distribution,
            "is_following": is_following,
            "is_self": request.user.is_authenticated and request.user.pk == analyst.pk,
            "latest_predictions": latest_predictions,
        },
    )


def _market_rows(queryset) -> list[dict]:
    rows = (
        queryset.values("market")
        .annotate(
            total=Count("id"),
            wins=Count("id", filter=Q(state_status=Prediction.StateStatus.WIN)),
            losses=Count("id", filter=Q(state_status=Prediction.StateStatus.LOSE)),
            refunds=Count("id", filter=Q(state_status=Prediction.StateStatus.REFUND)),
            avg_coefficient=Avg("coefficient"),
        )
        .order_by("-total", "market")[:8]
    )
    result = []
    for row in rows:
        settled = (row["wins"] or 0) + (row["losses"] or 0)
        result.append(
            {
                "label": MARKET_LABELS.get(row["market"], row["market"] or "Рынок"),
                "count": row["total"] or 0,
                "wins": row["wins"] or 0,
                "losses": row["losses"] or 0,
                "refunds": row["refunds"] or 0,
                "win_rate": round((row["wins"] or 0) / settled * 100) if settled else 0,
                "avg_coefficient": row["avg_coefficient"] or 0,
            }
        )
    return result


def _league_rows(queryset) -> list[dict]:
    rows = (
        queryset.values("match__league__name_ru", "match__league__name")
        .annotate(
            total=Count("id"),
            wins=Count("id", filter=Q(state_status=Prediction.StateStatus.WIN)),
            losses=Count("id", filter=Q(state_status=Prediction.StateStatus.LOSE)),
            refunds=Count("id", filter=Q(state_status=Prediction.StateStatus.REFUND)),
            avg_coefficient=Avg("coefficient"),
        )
        .order_by("-total", "match__league__name_ru")[:8]
    )
    result = []
    for row in rows:
        settled = (row["wins"] or 0) + (row["losses"] or 0)
        result.append(
            {
                "label": row["match__league__name_ru"] or row["match__league__name"] or "Лига не указана",
                "count": row["total"] or 0,
                "wins": row["wins"] or 0,
                "losses": row["losses"] or 0,
                "refunds": row["refunds"] or 0,
                "win_rate": round((row["wins"] or 0) / settled * 100) if settled else 0,
                "avg_coefficient": row["avg_coefficient"] or 0,
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
