from collections import defaultdict
from decimal import Decimal, InvalidOperation

from django import template
from django.core.cache import cache
from django.db.models import Q, Sum
from django.utils import timezone

from cabinet.models import AnalystProfile, CapperMonthlyStat, User


register = template.Library()
CAPPER_TABLE_HERO_CACHE_TTL = 60


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


def _shape_sparse_values(values: list[float]) -> list[float]:
    values = list(values[-8:])
    if not values:
        return [0.0, 0.0]
    if len(values) == 1:
        return [0.0, values[0]]
    return values


def _sparkline(values: list[float]) -> dict:
    values = _shape_sparse_values(values)

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

    current = values[-1]
    if current > 0:
        tone = "positive"
    elif current < 0:
        tone = "negative"
    else:
        tone = "neutral"

    return {"points": " ".join(points), "tone": tone}


@register.simple_tag
def capper_table_hero_stats() -> dict:
    current_month = timezone.localdate().replace(day=1)
    cache_key = f"capper-table:hero-stats:v1:{current_month.isoformat()}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    active_profiles = AnalystProfile.objects.filter(
        is_public=True,
        user__role=User.Role.ANALYST,
        user__is_active=True,
    )
    active_ids = active_profiles.values_list("user_id", flat=True)
    stats = CapperMonthlyStat.objects.filter(analyst_id__in=active_ids).aggregate(
        predictions_month=Sum("bets_count", filter=Q(month=current_month)),
        predictions_all_time=Sum("bets_count"),
    )

    result = {
        "active_cappers": _format_count(active_profiles.count()),
        "predictions_month": _format_count(stats["predictions_month"] or 0),
        "predictions_all_time": _format_count(stats["predictions_all_time"] or 0),
    }
    cache.set(cache_key, result, CAPPER_TABLE_HERO_CACHE_TTL)
    return result


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
