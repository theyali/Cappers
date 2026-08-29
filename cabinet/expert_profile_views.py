from decimal import Decimal, InvalidOperation

from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import ensure_csrf_cookie

from front.capper_stats_service import CapperStatsService
from front.prediction_views import _decorate_predictions, _published_queryset
from game.models import PredictionCoupon

from .models import AnalystProfile, CapperMonthlyStat, User


RECENT_PERFORMANCE_LIMITS = (10, 100)
RECENT_PERFORMANCE_STATES = (
    PredictionCoupon.StateStatus.WIN,
    PredictionCoupon.StateStatus.LOSE,
    PredictionCoupon.StateStatus.REFUND,
)
MONTH_NAMES_RU = (
    "",
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
)
SPORT_ORDER = {
    "football": 0,
    "hockey": 1,
    "basketball": 2,
    "tennis": 3,
}
SPORT_NAMES_RU = {
    "football": "Футбол",
    "hockey": "Хоккей",
    "basketball": "Баскетбол",
    "tennis": "Теннис",
}
SPORT_DECIMAL_FIELDS = (
    "allocated_stake",
    "allocated_profit",
    "flat_units",
    "weight",
    "coefficient_sum",
)
SPORT_INTEGER_FIELDS = (
    "predictions_count",
    "wins_count",
    "losses_count",
    "refunds_count",
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


def _decimal(value) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _percent(numerator: Decimal, denominator: Decimal) -> float:
    if denominator <= 0:
        return 0.0
    return round(float(numerator / denominator * Decimal("100")), 1)


def _prediction_count_text(count: int) -> str:
    value = abs(int(count))
    last_two = value % 100
    last = value % 10
    if 11 <= last_two <= 14:
        word = "прогнозов"
    elif last == 1:
        word = "прогноз"
    elif 2 <= last <= 4:
        word = "прогноза"
    else:
        word = "прогнозов"
    return f"{count} {word}"


def _empty_sport_bucket(code: str, name: str = "") -> dict:
    return {
        "code": code,
        "name": name or SPORT_NAMES_RU.get(code, code.capitalize()),
        "predictions_count": 0,
        "wins_count": 0,
        "losses_count": 0,
        "refunds_count": 0,
        "allocated_stake": Decimal("0"),
        "allocated_profit": Decimal("0"),
        "flat_units": Decimal("0"),
        "weight": Decimal("0"),
        "coefficient_sum": Decimal("0"),
    }


def _merge_sport_snapshot(target: dict[str, dict], snapshot: dict | None) -> None:
    if not isinstance(snapshot, dict):
        return
    for code, raw in snapshot.items():
        if not isinstance(raw, dict):
            continue
        code = str(raw.get("code") or code or "football")
        bucket = target.setdefault(
            code,
            _empty_sport_bucket(code, str(raw.get("name") or "")),
        )
        if raw.get("name"):
            bucket["name"] = str(raw["name"])
        for field in SPORT_INTEGER_FIELDS:
            bucket[field] += int(raw.get(field) or 0)
        for field in SPORT_DECIMAL_FIELDS:
            bucket[field] += _decimal(raw.get(field))


def _sport_rows(snapshot: dict | None) -> list[dict]:
    merged: dict[str, dict] = {}
    _merge_sport_snapshot(merged, snapshot)
    rows = []
    for code, bucket in merged.items():
        predictions_count = bucket["predictions_count"]
        states_total = (
            bucket["wins_count"]
            + bucket["losses_count"]
            + bucket["refunds_count"]
        )
        denominator = states_total or predictions_count
        profit_percent = _percent(bucket["flat_units"], bucket["weight"])
        roi = _percent(bucket["allocated_profit"], bucket["allocated_stake"])
        rows.append(
            {
                "code": code,
                "name": bucket["name"] or SPORT_NAMES_RU.get(code, code.capitalize()),
                "predictions_count": predictions_count,
                "predictions_text": _prediction_count_text(predictions_count),
                "wins_count": bucket["wins_count"],
                "losses_count": bucket["losses_count"],
                "refunds_count": bucket["refunds_count"],
                "win_percent": round(bucket["wins_count"] / denominator * 100, 1)
                if denominator
                else 0,
                "loss_percent": round(bucket["losses_count"] / denominator * 100, 1)
                if denominator
                else 0,
                "refund_percent": round(bucket["refunds_count"] / denominator * 100, 1)
                if denominator
                else 0,
                "profit_percent": profit_percent,
                "profit_display": f"{profit_percent:.1f}%",
                "roi": roi,
                "roi_display": f"{roi:.1f}%",
            }
        )
    return sorted(
        rows,
        key=lambda row: (
            SPORT_ORDER.get(row["code"], 100),
            row["name"].lower(),
        ),
    )


def _sport_profit_periods(rows: list[CapperMonthlyStat]) -> tuple[dict, list[dict]]:
    all_time: dict[str, dict] = {}
    periods: dict[str, dict] = {}
    options = [{"key": "all", "label": "все время"}]

    for row in rows:
        _merge_sport_snapshot(all_time, row.sports_data)
        key = row.month.strftime("%Y-%m")
        label = f"{MONTH_NAMES_RU[row.month.month].lower()} {row.month.year}"
        periods[key] = {
            "key": key,
            "label": label,
            "rows": _sport_rows(row.sports_data),
        }
        options.append({"key": key, "label": label})

    periods = {
        "all": {
            "key": "all",
            "label": "все время",
            "rows": _sport_rows(all_time),
        },
        **periods,
    }
    return periods, options


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
    sport_profit_periods, sport_profit_period_options = _sport_profit_periods(monthly_rows)
    context["sport_profit_periods"] = sport_profit_periods
    context["sport_profit_period_options"] = sport_profit_period_options
    context["sport_profit_default"] = sport_profit_periods["all"]

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
