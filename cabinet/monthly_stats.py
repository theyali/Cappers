from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, time
from decimal import Decimal, ROUND_HALF_UP

from django.db.models.functions import Coalesce
from django.utils import timezone

from game.models import PredictionCoupon

from .models import CapperMonthlyStat


SETTLED_STATES = {
    PredictionCoupon.StateStatus.WIN,
    PredictionCoupon.StateStatus.LOSE,
    PredictionCoupon.StateStatus.REFUND,
}
PERCENT_STEP = Decimal("0.01")
COEFFICIENT_STEP = Decimal("0.01")
MONEY_STEP = Decimal("0.01")
SPORT_FALLBACK_CODE = "football"
SPORT_FALLBACK_NAME = "Футбол"
SPORT_NAME_FALLBACKS = {
    "football": "Футбол",
    "hockey": "Хоккей",
    "basketball": "Баскетбол",
    "tennis": "Теннис",
}


def _local_datetime(value):
    if value is None:
        return None
    if timezone.is_aware(value):
        return timezone.localtime(value)
    return value


def coupon_result_at(coupon: PredictionCoupon):
    return (
        coupon.settled_at
        or coupon.updated_at
        or coupon.published_at
        or coupon.created_at
    )


def coupon_result_month(coupon: PredictionCoupon) -> date | None:
    result_at = _local_datetime(coupon_result_at(coupon))
    if result_at is None:
        return None
    return date(result_at.year, result_at.month, 1)


def monthly_stat_key(coupon: PredictionCoupon) -> tuple[int, date] | None:
    if (
        not coupon.author_id
        or coupon.published_status != PredictionCoupon.PublishedStatus.PUBLISHED
        or coupon.state_status not in SETTLED_STATES
    ):
        return None
    month = coupon_result_month(coupon)
    return (coupon.author_id, month) if month else None


def _next_month(month: date) -> date:
    if month.month == 12:
        return date(month.year + 1, 1, 1)
    return date(month.year, month.month + 1, 1)


def _aware_start(day: date):
    value = datetime.combine(day, time.min)
    if timezone.is_aware(timezone.now()):
        return timezone.make_aware(value, timezone.get_current_timezone())
    return value


def _coefficient(coupon: PredictionCoupon) -> Decimal:
    stake = coupon.total_stake or Decimal("0")
    payout = coupon.possible_payout or Decimal("0")
    if stake <= 0 or payout <= 0:
        return Decimal("0")
    return payout / stake


def _profit(coupon: PredictionCoupon) -> Decimal:
    stake = coupon.total_stake or Decimal("0")
    payout = coupon.possible_payout or Decimal("0")
    if coupon.state_status == PredictionCoupon.StateStatus.WIN:
        return payout - stake
    if coupon.state_status == PredictionCoupon.StateStatus.LOSE:
        return -stake
    return Decimal("0")


def _flat_units(coupon: PredictionCoupon) -> Decimal:
    if coupon.state_status == PredictionCoupon.StateStatus.LOSE:
        return Decimal("-1")
    if coupon.state_status == PredictionCoupon.StateStatus.REFUND:
        return Decimal("0")
    coefficient = _coefficient(coupon)
    return coefficient - Decimal("1") if coefficient > 0 else Decimal("0")


def _percent(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator <= 0:
        return Decimal("0")
    return (numerator / denominator * Decimal("100")).quantize(
        PERCENT_STEP,
        rounding=ROUND_HALF_UP,
    )


def _coupon_sports(coupon: PredictionCoupon) -> tuple[Counter, dict[str, str]]:
    counts = Counter()
    names: dict[str, str] = {}
    for item in coupon.predictions.all():
        sport = item.match.sport if item.match_id and item.match else None
        code = sport.code if sport else SPORT_FALLBACK_CODE
        name = (
            (sport.name_ru or sport.name)
            if sport
            else SPORT_FALLBACK_NAME
        ) or SPORT_NAME_FALLBACKS.get(code, code.capitalize())
        counts[code] += 1
        names[code] = name

    # Legacy predictions were football-only and some historical coupons can exist
    # without item rows. Preserve them in the football bucket instead of losing
    # their persisted history during the backfill/rebuild.
    if not counts:
        counts[SPORT_FALLBACK_CODE] = 1
        names[SPORT_FALLBACK_CODE] = SPORT_FALLBACK_NAME
    return counts, names


def _sports_snapshot(coupons: list[PredictionCoupon]) -> dict[str, dict]:
    buckets = defaultdict(
        lambda: {
            "name": "",
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
    )

    for coupon in coupons:
        counts, names = _coupon_sports(coupon)
        total_items = sum(counts.values()) or 1
        stake = coupon.total_stake or Decimal("0")
        profit = _profit(coupon)
        flat_units = _flat_units(coupon)
        coefficient = _coefficient(coupon)

        for code, item_count in counts.items():
            share = Decimal(item_count) / Decimal(total_items)
            bucket = buckets[code]
            bucket["name"] = names.get(code) or SPORT_NAME_FALLBACKS.get(code, code.capitalize())
            bucket["predictions_count"] += 1
            if coupon.state_status == PredictionCoupon.StateStatus.WIN:
                bucket["wins_count"] += 1
            elif coupon.state_status == PredictionCoupon.StateStatus.LOSE:
                bucket["losses_count"] += 1
            else:
                bucket["refunds_count"] += 1
            bucket["allocated_stake"] += stake * share
            bucket["allocated_profit"] += profit * share
            bucket["flat_units"] += flat_units * share
            bucket["weight"] += share
            if coefficient > 0:
                bucket["coefficient_sum"] += coefficient * share

    payload: dict[str, dict] = {}
    for code, bucket in sorted(buckets.items(), key=lambda item: item[0]):
        payload[code] = {
            "code": code,
            "name": bucket["name"],
            "predictions_count": bucket["predictions_count"],
            "wins_count": bucket["wins_count"],
            "losses_count": bucket["losses_count"],
            "refunds_count": bucket["refunds_count"],
            "allocated_stake": str(
                bucket["allocated_stake"].quantize(MONEY_STEP, rounding=ROUND_HALF_UP)
            ),
            "allocated_profit": str(
                bucket["allocated_profit"].quantize(MONEY_STEP, rounding=ROUND_HALF_UP)
            ),
            "flat_units": str(
                bucket["flat_units"].quantize(PERCENT_STEP, rounding=ROUND_HALF_UP)
            ),
            "weight": str(bucket["weight"].quantize(PERCENT_STEP, rounding=ROUND_HALF_UP)),
            "coefficient_sum": str(
                bucket["coefficient_sum"].quantize(
                    COEFFICIENT_STEP,
                    rounding=ROUND_HALF_UP,
                )
            ),
        }
    return payload


def rebuild_capper_month(analyst_id: int, month: date) -> CapperMonthlyStat | None:
    """Rebuild one persisted monthly snapshot from canonical settled predictions."""
    month = date(month.year, month.month, 1)
    start = _aware_start(month)
    end = _aware_start(_next_month(month))

    coupons = list(
        PredictionCoupon.objects.filter(
            author_id=analyst_id,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status__in=SETTLED_STATES,
        )
        .annotate(
            result_at=Coalesce(
                "settled_at",
                "updated_at",
                "published_at",
                "created_at",
            )
        )
        .filter(result_at__gte=start, result_at__lt=end)
        .prefetch_related("predictions__match__sport")
        .order_by("result_at", "id")
    )

    if not coupons:
        CapperMonthlyStat.objects.filter(analyst_id=analyst_id, month=month).delete()
        return None

    bets_count = len(coupons)
    wins_count = sum(
        coupon.state_status == PredictionCoupon.StateStatus.WIN for coupon in coupons
    )
    losses_count = sum(
        coupon.state_status == PredictionCoupon.StateStatus.LOSE for coupon in coupons
    )
    refunds_count = sum(
        coupon.state_status == PredictionCoupon.StateStatus.REFUND for coupon in coupons
    )

    total_stake = sum(
        (coupon.total_stake or Decimal("0") for coupon in coupons),
        Decimal("0"),
    )
    total_profit = sum((_profit(coupon) for coupon in coupons), Decimal("0"))
    flat_units = sum((_flat_units(coupon) for coupon in coupons), Decimal("0"))

    coefficients = [value for value in (_coefficient(coupon) for coupon in coupons) if value > 0]
    avg_coefficient = (
        sum(coefficients, Decimal("0")) / Decimal(len(coefficients))
        if coefficients
        else Decimal("0")
    )

    stat, _ = CapperMonthlyStat.objects.update_or_create(
        analyst_id=analyst_id,
        month=month,
        defaults={
            "bets_count": bets_count,
            "wins_count": wins_count,
            "losses_count": losses_count,
            "refunds_count": refunds_count,
            "total_stake": total_stake.quantize(MONEY_STEP, rounding=ROUND_HALF_UP),
            "total_profit": total_profit.quantize(MONEY_STEP, rounding=ROUND_HALF_UP),
            "flat_profit_percent": _percent(flat_units, Decimal(bets_count)),
            "roi": _percent(total_profit, total_stake),
            "avg_coefficient": avg_coefficient.quantize(
                COEFFICIENT_STEP,
                rounding=ROUND_HALF_UP,
            ),
            "hit_rate": _percent(Decimal(wins_count), Decimal(bets_count)),
            "sports_data": _sports_snapshot(coupons),
        },
    )
    return stat
