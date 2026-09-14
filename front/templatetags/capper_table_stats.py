from collections import defaultdict
from decimal import Decimal, InvalidOperation

from django import template
from django.db.models import Sum
from django.utils import timezone

from cabinet.models import AnalystProfile, CapperMonthlyStat, User


register = template.Library()


def _format_count(value) -> str:
    return f"{int(value or 0):,}".replace(",", " ")


def _decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _sport_roi(stat: CapperMonthlyStat, sport_code: str) -> float:
    if sport_code == "all":
        return float(_decimal(stat.roi))

    payload = (stat.sports_data or {}).get(sport_code)
    if not isinstance(payload, dict):
        return 0.0

    stake = _decimal(payload.get("allocated_stake"))
    if stake <= 0:
        return 0.0
    profit = _decimal(payload.get("allocated_profit"))
    return float(profit / stake * Decimal("100"))


def _sparkline(values: list[float]) -> dict:
    values = list(values[-8:])
    if not values:
        values = [0.0, 0.0]
    elif len(values) == 1:
        values = [values[0], values[0]]

    width = 88.0
    height = 34.0
    padding = 3.0
    low = min(values)
    high = max(values)
    if high == low:
        high += 1.0
        low -= 1.0

    step = (width - padding * 2) / max(len(values) - 1, 1)
    usable_height = height - padding * 2
    points = []
    for index, value in enumerate(values):
        x = padding + step * index
        y = padding + ((high - value) / (high - low)) * usable_height
        points.append(f"{x:.1f},{y:.1f}")

    delta = values[-1] - values[0]
    if delta > 0:
        tone = "positive"
    elif delta < 0:
        tone = "negative"
    else:
        tone = "positive" if values[-1] > 0 else "negative" if values[-1] < 0 else "neutral"

    return {"points": " ".join(points), "tone": tone}


@register.simple_tag
def capper_table_hero_stats() -> dict:
    active_profiles = AnalystProfile.objects.filter(
        is_public=True,
        user__role=User.Role.ANALYST,
        user__is_active=True,
    )
    active_ids = active_profiles.values_list("user_id", flat=True)
    stats = CapperMonthlyStat.objects.filter(analyst_id__in=active_ids)
    current_month = timezone.localdate().replace(day=1)

    predictions_month = (
        stats.filter(month=current_month).aggregate(total=Sum("bets_count"))["total"] or 0
    )
    predictions_all_time = stats.aggregate(total=Sum("bets_count"))["total"] or 0

    return {
        "active_cappers": _format_count(active_profiles.count()),
        "predictions_month": _format_count(predictions_month),
        "predictions_all_time": _format_count(predictions_all_time),
    }


@register.simple_tag
def capper_table_trends(rows, sport_code="all") -> dict:
    analyst_ids = [int(row.get("id")) for row in rows if row.get("id")]
    if not analyst_ids:
        return {}

    values_by_analyst = defaultdict(list)
    stats = (
        CapperMonthlyStat.objects.filter(analyst_id__in=analyst_ids)
        .only("analyst_id", "month", "roi", "sports_data")
        .order_by("analyst_id", "month")
    )
    for stat in stats:
        values_by_analyst[stat.analyst_id].append(_sport_roi(stat, sport_code))

    return {
        analyst_id: _sparkline(values)
        for analyst_id, values in values_by_analyst.items()
    }


@register.filter
def dict_get(mapping, key):
    if not isinstance(mapping, dict):
        return None
    return mapping.get(key)


@register.filter
def compact_count(value) -> str:
    number = int(value or 0)
    absolute = abs(number)
    if absolute >= 1_000_000:
        return f"{number / 1_000_000:.1f}M".replace(".0M", "M")
    if absolute >= 1_000:
        return f"{number / 1_000:.1f}K".replace(".0K", "K")
    return str(number)
