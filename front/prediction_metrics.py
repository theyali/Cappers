from datetime import timedelta
from decimal import Decimal

from django.db.models import (
    Case,
    DecimalField,
    ExpressionWrapper,
    F,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from django.utils import timezone

from game.models import PredictionCoupon


ROI_PERIOD_DAYS = 30
SETTLED_COUPON_STATES = (
    PredictionCoupon.StateStatus.WIN,
    PredictionCoupon.StateStatus.LOSE,
    PredictionCoupon.StateStatus.REFUND,
)


def roi_period_q(*, prefix: str = "", days: int = ROI_PERIOD_DAYS) -> Q:
    """Settled coupon activity included in a public ROI period.

    ``settled_at`` is the canonical result date. ``updated_at`` is only a
    fallback for older settled rows that do not have ``settled_at`` filled.
    """
    cutoff = timezone.now() - timedelta(days=days)
    settled_at = f"{prefix}settled_at"
    updated_at = f"{prefix}updated_at"
    return Q(**{f"{settled_at}__gte": cutoff}) | Q(
        **{
            f"{settled_at}__isnull": True,
            f"{updated_at}__gte": cutoff,
        }
    )


def author_roi_subquery(
    author_outer_ref: str = "coupon__author_id",
    *,
    period_days: int | None = ROI_PERIOD_DAYS,
):
    money_field = DecimalField(max_digits=18, decimal_places=4)
    profit_expression = Case(
        When(
            state_status=PredictionCoupon.StateStatus.WIN,
            then=F("possible_payout") - F("total_stake"),
        ),
        When(
            state_status=PredictionCoupon.StateStatus.LOSE,
            then=-F("total_stake"),
        ),
        default=Value(Decimal("0")),
        output_field=money_field,
    )
    queryset = PredictionCoupon.objects.filter(
        author_id=OuterRef(author_outer_ref),
        published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        state_status__in=SETTLED_COUPON_STATES,
        total_stake__gt=0,
    )
    if period_days is not None:
        queryset = queryset.filter(roi_period_q(days=period_days))

    return (
        queryset.values("author_id")
        .annotate(
            roi_profit=Sum(profit_expression),
            roi_stake=Sum("total_stake"),
        )
        .annotate(
            roi_value=ExpressionWrapper(
                F("roi_profit") * Value(Decimal("100")) / F("roi_stake"),
                output_field=DecimalField(max_digits=12, decimal_places=4),
            )
        )
        .values("roi_value")[:1]
    )


def annotate_author_roi(
    queryset,
    *,
    author_outer_ref: str = "coupon__author_id",
    annotation_name: str = "author_roi",
    period_days: int | None = ROI_PERIOD_DAYS,
):
    roi_field = DecimalField(max_digits=12, decimal_places=4)
    return queryset.annotate(
        **{
            annotation_name: Coalesce(
                Subquery(
                    author_roi_subquery(
                        author_outer_ref,
                        period_days=period_days,
                    ),
                    output_field=roi_field,
                ),
                Value(Decimal("0")),
                output_field=roi_field,
            )
        }
    )
