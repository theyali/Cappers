from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable

from game.models import PredictionCoupon


BUCKETS = (
    (0, 49, "0-49%"),
    (50, 59, "50-59%"),
    (60, 69, "60-69%"),
    (70, 79, "70-79%"),
    (80, 89, "80-89%"),
    (90, 100, "90-100%"),
)
DECIDED_STATES = {
    PredictionCoupon.StateStatus.WIN,
    PredictionCoupon.StateStatus.LOSE,
}
MIN_RELIABLE_SAMPLE = 5
FULL_RELIABLE_SAMPLE = 20
GOOD_ERROR_LIMIT = Decimal("5.0")
WARNING_ERROR_LIMIT = Decimal("15.0")


def build_confidence_calibration(coupons: Iterable[PredictionCoupon]) -> dict:
    buckets = _empty_buckets()

    for coupon in coupons:
        _add_coupon_to_buckets(
            buckets,
            confidence=coupon.confidence,
            state_status=coupon.state_status,
        )

    return _build_calibration_from_buckets(buckets)


def build_confidence_calibration_by_author(author_ids: Iterable[int]) -> dict[int, dict]:
    ids = list(dict.fromkeys(author_id for author_id in author_ids if author_id))
    if not ids:
        return {}

    grouped_buckets = {author_id: _empty_buckets() for author_id in ids}
    rows = PredictionCoupon.objects.filter(
        author_id__in=ids,
        published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
    ).values_list("author_id", "confidence", "state_status")

    for author_id, confidence, state_status in rows:
        _add_coupon_to_buckets(
            grouped_buckets[author_id],
            confidence=confidence,
            state_status=state_status,
        )

    return {
        author_id: _build_calibration_from_buckets(buckets)
        for author_id, buckets in grouped_buckets.items()
    }


def _empty_buckets() -> dict:
    return {
        label: {
            "label": label,
            "lower": lower,
            "upper": upper,
            "wins": 0,
            "losses": 0,
            "refunds": 0,
            "confidence_sum": Decimal("0"),
        }
        for lower, upper, label in BUCKETS
    }


def _add_coupon_to_buckets(
    buckets: dict,
    *,
    confidence: int | None,
    state_status: str,
) -> None:
    bucket = _bucket_for(confidence)
    if bucket is None:
        return

    row = buckets[bucket]
    if state_status == PredictionCoupon.StateStatus.WIN:
        row["wins"] += 1
        row["confidence_sum"] += Decimal(confidence)
    elif state_status == PredictionCoupon.StateStatus.LOSE:
        row["losses"] += 1
        row["confidence_sum"] += Decimal(confidence)
    elif state_status == PredictionCoupon.StateStatus.REFUND:
        row["refunds"] += 1


def _build_calibration_from_buckets(buckets: dict) -> dict:
    rows = []
    total_decided = 0
    total_refunds = 0
    weighted_abs_error = Decimal("0")
    weighted_delta = Decimal("0")

    for _, _, label in BUCKETS:
        row = buckets[label]
        decided = row["wins"] + row["losses"]
        total_refunds += row["refunds"]
        if decided <= 0:
            continue

        declared_rate = _average_decimal(row["confidence_sum"], decided)
        actual_rate = _percent_decimal(row["wins"], decided)
        delta = actual_rate - declared_rate
        abs_delta = abs(delta)
        total_decided += decided
        weighted_abs_error += abs_delta * decided
        weighted_delta += delta * decided
        rows.append(
            {
                "label": label,
                "wins": row["wins"],
                "losses": row["losses"],
                "refunds": row["refunds"],
                "total": decided,
                "declared_rate": _float(declared_rate),
                "actual_rate": _float(actual_rate),
                "delta": _float(delta),
                "abs_delta": _float(abs_delta),
                "actual_rate_width": _width(actual_rate),
                "declared_rate_width": _width(declared_rate),
                "accuracy_tone": _accuracy_tone(delta, abs_delta),
                "is_reliable": decided >= MIN_RELIABLE_SAMPLE,
                "is_full_sample": decided >= FULL_RELIABLE_SAMPLE,
                "sample_label": _sample_label(decided),
            }
        )

    average_abs_error = _average_decimal(weighted_abs_error, total_decided)
    average_delta = _average_decimal(weighted_delta, total_decided)
    strongest_row = max(rows, key=lambda row: (row["total"], row["label"]), default=None)

    return {
        "rows": rows,
        "total": total_decided,
        "refunds": total_refunds,
        "average_abs_error": _float(average_abs_error),
        "average_delta": _float(average_delta),
        "average_delta_label": _delta_label(average_delta),
        "accuracy_tone": _accuracy_tone(average_delta, average_abs_error),
        "accuracy_label": _accuracy_label(average_delta, average_abs_error),
        "strongest_row": strongest_row,
        "has_data": bool(rows),
        "has_reliable_data": any(row["is_reliable"] for row in rows),
        "min_reliable_sample": MIN_RELIABLE_SAMPLE,
        "full_reliable_sample": FULL_RELIABLE_SAMPLE,
    }


def _bucket_for(confidence: int | None) -> str | None:
    if confidence is None:
        return None
    confidence = max(0, min(100, int(confidence)))
    for lower, upper, label in BUCKETS:
        if lower <= confidence <= upper:
            return label
    return None


def _percent_decimal(value, total: int) -> Decimal:
    if not total:
        return Decimal("0.0")
    return (Decimal(value) / Decimal(total) * Decimal("100")).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def _average_decimal(value: Decimal, total: int) -> Decimal:
    if not total:
        return Decimal("0.0")
    return (Decimal(value) / Decimal(total)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def _float(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def _width(value: Decimal) -> int:
    return max(0, min(100, int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))))


def _delta_label(delta: Decimal) -> str:
    delta = delta.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    if delta > 0:
        return f"занижает на {_format_decimal(abs(delta))} п.п."
    if delta < 0:
        return f"завышает на {_format_decimal(abs(delta))} п.п."
    return "совпадает с фактом"


def _accuracy_tone(delta: Decimal, abs_delta: Decimal) -> str:
    if abs_delta <= GOOD_ERROR_LIMIT:
        return "success"
    if abs_delta <= WARNING_ERROR_LIMIT:
        return "warning"
    if delta < 0:
        return "danger"
    return "warning"


def _accuracy_label(delta: Decimal, abs_delta: Decimal) -> str:
    if abs_delta <= GOOD_ERROR_LIMIT:
        return "точная оценка"
    if abs_delta <= WARNING_ERROR_LIMIT:
        return "среднее отклонение"
    if delta < 0:
        return "сильное завышение"
    return "сильное занижение"


def _sample_label(total: int) -> str:
    if total < MIN_RELIABLE_SAMPLE:
        return "Недостаточно данных"
    if total < FULL_RELIABLE_SAMPLE:
        return "Малая выборка"
    return "Надежная выборка"


def _format_decimal(value: Decimal) -> str:
    return str(value).replace(".", ",")
