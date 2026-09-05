from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from math import sqrt
from statistics import pstdev

from django.db.models.functions import Coalesce
from django.utils import timezone

from game.models import PredictionCoupon

from .confidence_calibration import build_confidence_calibration
from .models import AnalystProfile


SETTLED_STATES = {
    PredictionCoupon.StateStatus.WIN,
    PredictionCoupon.StateStatus.LOSE,
    PredictionCoupon.StateStatus.REFUND,
}
SCORE_STEP = Decimal("0.1")
WEIGHTS = {
    "roi": Decimal("2.2"),
    "distance": Decimal("1.5"),
    "drawdown": Decimal("1.3"),
    "stability": Decimal("1.2"),
    "avg_coefficient": Decimal("0.8"),
    "frequency": Decimal("1.0"),
    "confidence": Decimal("2.0"),
}


@dataclass(frozen=True)
class TrustIndexResult:
    trust_index: Decimal
    components: dict[str, Decimal]
    metrics: dict[str, Decimal | int | None]


class CapperTrustIndexService:
    """Calculate and persist the public trust index for one capper."""

    def __init__(self, analyst_id: int):
        self.analyst_id = analyst_id

    def calculate(self) -> TrustIndexResult:
        published_coupons = self._published_coupons()
        settled_coupons = [
            coupon
            for coupon in published_coupons
            if coupon.state_status in SETTLED_STATES
        ]
        settled_count = len(settled_coupons)

        if settled_count <= 0:
            return TrustIndexResult(
                trust_index=Decimal("0.0"),
                components=self._empty_components(),
                metrics={
                    "settled_count": 0,
                    "published_30d_count": self._recent_publication_count(published_coupons),
                    "roi": Decimal("0.0"),
                    "total_stake": Decimal("0.00"),
                    "total_profit": Decimal("0.00"),
                    "max_drawdown_percent": Decimal("0.0"),
                    "avg_coefficient": Decimal("0.00"),
                    "confidence_average_abs_error": None,
                },
            )

        total_stake = sum(
            (coupon.total_stake or Decimal("0") for coupon in settled_coupons),
            Decimal("0"),
        )
        total_profit = sum(
            (self._coupon_profit(coupon) for coupon in settled_coupons),
            Decimal("0"),
        )
        roi = self._percent(total_profit, total_stake)
        max_drawdown_percent = self._max_drawdown_percent(settled_coupons, total_stake)
        avg_coefficient = self._avg_coefficient(published_coupons)
        published_30d_count = self._recent_publication_count(published_coupons)
        confidence_error = self._confidence_average_abs_error(published_coupons)

        components = {
            "roi": self._score_by_points(
                roi,
                [
                    (Decimal("-20"), Decimal("0")),
                    (Decimal("-10"), Decimal("2")),
                    (Decimal("0"), Decimal("4")),
                    (Decimal("10"), Decimal("6")),
                    (Decimal("20"), Decimal("8")),
                    (Decimal("35"), Decimal("10")),
                ],
            ),
            "distance": self._distance_score(settled_count),
            "drawdown": self._score_by_points(
                max_drawdown_percent,
                [
                    (Decimal("0"), Decimal("10")),
                    (Decimal("5"), Decimal("10")),
                    (Decimal("10"), Decimal("8")),
                    (Decimal("20"), Decimal("5")),
                    (Decimal("35"), Decimal("2")),
                    (Decimal("50"), Decimal("0")),
                ],
            ),
            "stability": self._stability_score(settled_coupons),
            "avg_coefficient": self._avg_coefficient_score(avg_coefficient),
            "frequency": self._score_by_points(
                Decimal(published_30d_count),
                [
                    (Decimal("0"), Decimal("0")),
                    (Decimal("1"), Decimal("2")),
                    (Decimal("4"), Decimal("5")),
                    (Decimal("8"), Decimal("8")),
                    (Decimal("12"), Decimal("10")),
                ],
            ),
            "confidence": self._confidence_score(confidence_error),
        }

        raw_index = sum(
            components[name] * weight / Decimal("10")
            for name, weight in WEIGHTS.items()
        )
        capped_index = min(raw_index, self._sample_cap(settled_count))

        return TrustIndexResult(
            trust_index=self._round_score(capped_index),
            components={name: self._round_score(value) for name, value in components.items()},
            metrics={
                "settled_count": settled_count,
                "published_30d_count": published_30d_count,
                "roi": roi.quantize(SCORE_STEP, rounding=ROUND_HALF_UP),
                "total_stake": total_stake.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                "total_profit": total_profit.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                "max_drawdown_percent": max_drawdown_percent.quantize(
                    SCORE_STEP,
                    rounding=ROUND_HALF_UP,
                ),
                "avg_coefficient": avg_coefficient.quantize(
                    Decimal("0.01"),
                    rounding=ROUND_HALF_UP,
                ),
                "confidence_average_abs_error": (
                    confidence_error.quantize(SCORE_STEP, rounding=ROUND_HALF_UP)
                    if confidence_error is not None
                    else None
                ),
            },
        )

    def refresh(self) -> AnalystProfile | None:
        profile = AnalystProfile.objects.filter(user_id=self.analyst_id).first()
        if profile is None:
            return None

        result = self.calculate()
        now = timezone.now()
        AnalystProfile.objects.filter(pk=profile.pk).update(
            trust_index=result.trust_index,
            trust_index_updated_at=now,
        )
        profile.trust_index = result.trust_index
        profile.trust_index_updated_at = now
        return profile

    def _published_coupons(self) -> list[PredictionCoupon]:
        return list(
            PredictionCoupon.objects.filter(
                author_id=self.analyst_id,
                published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            )
            .annotate(
                result_at=Coalesce(
                    "settled_at",
                    "updated_at",
                    "published_at",
                    "created_at",
                )
            )
            .order_by("result_at", "id")
        )

    @staticmethod
    def _coupon_profit(coupon: PredictionCoupon) -> Decimal:
        stake = coupon.total_stake or Decimal("0")
        payout = coupon.possible_payout or Decimal("0")
        if coupon.state_status == PredictionCoupon.StateStatus.WIN:
            return payout - stake
        if coupon.state_status == PredictionCoupon.StateStatus.LOSE:
            return -stake
        return Decimal("0")

    @staticmethod
    def _percent(numerator: Decimal, denominator: Decimal) -> Decimal:
        if denominator <= 0:
            return Decimal("0.0")
        return numerator / denominator * Decimal("100")

    @staticmethod
    def _score_by_points(
        value: Decimal,
        points: list[tuple[Decimal, Decimal]],
    ) -> Decimal:
        value = Decimal(value)
        if value <= points[0][0]:
            return points[0][1]

        for index in range(1, len(points)):
            left_x, left_score = points[index - 1]
            right_x, right_score = points[index]
            if value <= right_x:
                distance = right_x - left_x
                if distance <= 0:
                    return right_score
                progress = (value - left_x) / distance
                return left_score + (right_score - left_score) * progress

        return points[-1][1]

    @staticmethod
    def _distance_score(settled_count: int) -> Decimal:
        return min(Decimal("10"), Decimal(str(sqrt(settled_count / 100))) * Decimal("10"))

    def _max_drawdown_percent(
        self,
        coupons: list[PredictionCoupon],
        total_stake: Decimal,
    ) -> Decimal:
        if total_stake <= 0:
            return Decimal("0.0")

        balance = Decimal("0")
        peak = Decimal("0")
        max_drawdown = Decimal("0")
        for coupon in coupons:
            balance += self._coupon_profit(coupon)
            peak = max(peak, balance)
            max_drawdown = max(max_drawdown, peak - balance)
        return self._percent(max_drawdown, total_stake)

    @staticmethod
    def _avg_coefficient(coupons: list[PredictionCoupon]) -> Decimal:
        coefficients = []
        for coupon in coupons:
            stake = coupon.total_stake or Decimal("0")
            payout = coupon.possible_payout or Decimal("0")
            if stake > 0 and payout > 0:
                coefficients.append(payout / stake)
        if not coefficients:
            return Decimal("0.00")
        return sum(coefficients, Decimal("0")) / Decimal(len(coefficients))

    @staticmethod
    def _avg_coefficient_score(value: Decimal) -> Decimal:
        if Decimal("1.60") <= value <= Decimal("2.40"):
            return Decimal("10")
        if Decimal("1.40") <= value <= Decimal("1.59"):
            return Decimal("8")
        if Decimal("2.41") <= value <= Decimal("3.00"):
            return Decimal("8")
        if Decimal("1.20") <= value <= Decimal("1.39"):
            return Decimal("5")
        if Decimal("3.01") <= value <= Decimal("4.00"):
            return Decimal("5")
        if Decimal("1.01") <= value <= Decimal("1.19"):
            return Decimal("2")
        if Decimal("4.01") <= value <= Decimal("6.00"):
            return Decimal("2")
        return Decimal("0")

    def _stability_score(self, coupons: list[PredictionCoupon]) -> Decimal:
        months = defaultdict(lambda: {"profit": Decimal("0"), "stake": Decimal("0"), "count": 0})
        for coupon in coupons:
            result_at = (
                timezone.localtime(coupon.result_at)
                if timezone.is_aware(coupon.result_at)
                else coupon.result_at
            )
            month = (result_at.year, result_at.month)
            months[month]["profit"] += self._coupon_profit(coupon)
            months[month]["stake"] += coupon.total_stake or Decimal("0")
            months[month]["count"] += 1

        active_months = [
            values
            for values in months.values()
            if values["count"] >= 3 and values["stake"] > 0
        ]
        if len(active_months) < 2:
            return Decimal("5.0")

        monthly_roi_values = [
            float(self._percent(values["profit"], values["stake"]))
            for values in active_months
        ]
        monthly_roi_stddev = Decimal(str(pstdev(monthly_roi_values)))
        positive_month_share = (
            Decimal(sum(1 for values in active_months if values["profit"] > 0))
            / Decimal(len(active_months))
        )

        stddev_score = self._clamp(Decimal("10") - monthly_roi_stddev / Decimal("6"))
        positive_month_score = positive_month_share * Decimal("10")
        return stddev_score * Decimal("0.7") + positive_month_score * Decimal("0.3")

    @staticmethod
    def _recent_publication_count(coupons: list[PredictionCoupon]) -> int:
        cutoff = timezone.now() - timedelta(days=30)
        return sum(
            1
            for coupon in coupons
            if (coupon.published_at or coupon.created_at) >= cutoff
        )

    @staticmethod
    def _confidence_average_abs_error(coupons: list[PredictionCoupon]) -> Decimal | None:
        calibration = build_confidence_calibration(coupons)
        if not calibration["has_data"]:
            return None
        return Decimal(str(calibration["average_abs_error"]))

    def _confidence_score(self, average_abs_error: Decimal | None) -> Decimal:
        if average_abs_error is None:
            return Decimal("5.0")
        return self._score_by_points(
            average_abs_error,
            [
                (Decimal("0"), Decimal("10")),
                (Decimal("5"), Decimal("10")),
                (Decimal("15"), Decimal("6")),
                (Decimal("30"), Decimal("0")),
            ],
        )

    @staticmethod
    def _sample_cap(settled_count: int) -> Decimal:
        if settled_count <= 0:
            return Decimal("0.0")
        if settled_count <= 4:
            return Decimal("4.0")
        if settled_count <= 19:
            return Decimal("6.0")
        if settled_count <= 49:
            return Decimal("8.0")
        return Decimal("10.0")

    @staticmethod
    def _clamp(value: Decimal) -> Decimal:
        return max(Decimal("0"), min(Decimal("10"), value))

    @staticmethod
    def _round_score(value: Decimal) -> Decimal:
        return max(Decimal("0.0"), min(Decimal("10.0"), value)).quantize(
            SCORE_STEP,
            rounding=ROUND_HALF_UP,
        )

    @staticmethod
    def _empty_components() -> dict[str, Decimal]:
        return {name: Decimal("0.0") for name in WEIGHTS}


def calculate_capper_trust_index(analyst_id: int) -> TrustIndexResult:
    return CapperTrustIndexService(analyst_id).calculate()


def refresh_capper_trust_index(analyst_id: int) -> AnalystProfile | None:
    return CapperTrustIndexService(analyst_id).refresh()
