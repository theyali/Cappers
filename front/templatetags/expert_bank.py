from decimal import Decimal

from django import template

from wallets.models import CapperBankStats


register = template.Library()


@register.inclusion_tag("cabinet/_expert_public_bank.html")
def expert_public_bank(expert):
    stats = CapperBankStats.objects.filter(user=expert).first()
    zero = Decimal("0")

    if stats is None:
        return {
            "bank_coupons_count": 0,
            "bank_settled_count": 0,
            "bank_total_stake": zero,
            "bank_average_stake": zero,
            "bank_lost_amount": zero,
            "bank_earned_amount": zero,
            "bank_pending_stake": zero,
            "bank_net_result": zero,
        }

    return {
        "bank_coupons_count": stats.coupons_count,
        "bank_settled_count": stats.settled_count,
        "bank_total_stake": stats.total_stake,
        "bank_average_stake": stats.average_stake,
        "bank_lost_amount": stats.lost_amount,
        "bank_earned_amount": stats.earned_amount,
        "bank_pending_stake": stats.pending_stake,
        "bank_net_result": stats.net_result,
    }
