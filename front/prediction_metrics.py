from decimal import Decimal

from django.db.models import (
    Case,
    DecimalField,
    ExpressionWrapper,
    F,
    OuterRef,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce

from game.models import PredictionCoupon


SETTLED_COUPON_STATES = (
    PredictionCoupon.StateStatus.WIN,
    PredictionCoupon.StateStatus.LOSE,
    PredictionCoupon.StateStatus.REFUND,
)


def author_roi_subquery():
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
    return (
        PredictionCoupon.objects.filter(
            author_id=OuterRef("coupon__author_id"),
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status__in=SETTLED_COUPON_STATES,
            total_stake__gt=0,
        )
        .values("author_id")
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


def annotate_author_roi(queryset):
    roi_field = DecimalField(max_digits=12, decimal_places=4)
    return queryset.annotate(
        author_roi=Coalesce(
            Subquery(author_roi_subquery(), output_field=roi_field),
            Value(Decimal("0")),
            output_field=roi_field,
        )
    )
