from decimal import Decimal

from django.db.models import Avg, Count, DecimalField, ExpressionWrapper, F, Q, Sum

from game.models import PredictionCoupon

from .models import CapperBankStats


ZERO = Decimal("0")
SETTLED_STATES = (
    PredictionCoupon.StateStatus.WIN,
    PredictionCoupon.StateStatus.LOSE,
    PredictionCoupon.StateStatus.REFUND,
)


def empty_capper_bank_stats() -> dict:
    return {
        "coupons_count": 0,
        "settled_count": 0,
        "total_stake": ZERO,
        "average_stake": ZERO,
        "lost_amount": ZERO,
        "earned_amount": ZERO,
        "pending_stake": ZERO,
        "net_result": ZERO,
    }


def calculate_capper_bank_stats(user_id: int) -> dict:
    published = PredictionCoupon.objects.filter(
        author_id=user_id,
        published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
    )
    win_profit = ExpressionWrapper(
        F("possible_payout") - F("total_stake"),
        output_field=DecimalField(max_digits=18, decimal_places=2),
    )
    stats = published.aggregate(
        coupons_count=Count("id"),
        stake_sum=Sum("total_stake"),
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
            filter=Q(state_status__in=SETTLED_STATES),
        ),
    )

    total_stake = stats["stake_sum"] or ZERO
    average_stake = stats["average_stake"] or ZERO
    lost_amount = stats["lost_amount"] or ZERO
    earned_amount = stats["earned_amount"] or ZERO
    pending_stake = stats["pending_stake"] or ZERO

    return {
        "coupons_count": stats["coupons_count"] or 0,
        "settled_count": stats["settled_count"] or 0,
        "total_stake": total_stake,
        "average_stake": average_stake,
        "lost_amount": lost_amount,
        "earned_amount": earned_amount,
        "pending_stake": pending_stake,
        "net_result": earned_amount - lost_amount,
    }


def refresh_capper_bank_stats(user_id: int) -> CapperBankStats:
    values = calculate_capper_bank_stats(user_id)
    stats, _ = CapperBankStats.objects.update_or_create(
        user_id=user_id,
        defaults=values,
    )
    return stats


def ensure_empty_capper_bank_stats(user_id: int) -> CapperBankStats:
    stats, _ = CapperBankStats.objects.get_or_create(
        user_id=user_id,
        defaults=empty_capper_bank_stats(),
    )
    return stats
