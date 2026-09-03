from decimal import Decimal

from django import template
from django.db.models import Avg, Count, DecimalField, ExpressionWrapper, F, Q, Sum

from game.models import PredictionCoupon


register = template.Library()


@register.inclusion_tag("cabinet/_expert_public_bank.html")
def expert_public_bank(expert):
    published = PredictionCoupon.objects.filter(
        author=expert,
        published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
    )

    win_profit = ExpressionWrapper(
        F("possible_payout") - F("total_stake"),
        output_field=DecimalField(max_digits=18, decimal_places=2),
    )
    stats = published.aggregate(
        coupons_count=Count("id"),
        total_stake=Sum("total_stake"),
        average_stake=Avg("total_stake"),
        lost_amount=Sum(
            "total_stake",
            filter=Q(state_status=PredictionCoupon.StateStatus.LOSE),
        ),
        earned_amount=Sum(
            win_profit,
            filter=Q(state_status=PredictionCoupon.StateStatus.WIN),
        ),
        pending_stake=Sum(
            "total_stake",
            filter=Q(state_status=PredictionCoupon.StateStatus.PENDING),
        ),
        settled_count=Count(
            "id",
            filter=Q(
                state_status__in=(
                    PredictionCoupon.StateStatus.WIN,
                    PredictionCoupon.StateStatus.LOSE,
                    PredictionCoupon.StateStatus.REFUND,
                )
            ),
        ),
    )

    zero = Decimal("0")
    total_stake = stats["total_stake"] or zero
    average_stake = stats["average_stake"] or zero
    lost_amount = stats["lost_amount"] or zero
    earned_amount = stats["earned_amount"] or zero
    pending_stake = stats["pending_stake"] or zero
    net_result = earned_amount - lost_amount

    return {
        "bank_coupons_count": stats["coupons_count"] or 0,
        "bank_settled_count": stats["settled_count"] or 0,
        "bank_total_stake": total_stake,
        "bank_average_stake": average_stake,
        "bank_lost_amount": lost_amount,
        "bank_earned_amount": earned_amount,
        "bank_pending_stake": pending_stake,
        "bank_net_result": net_result,
    }
