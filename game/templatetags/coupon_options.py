from django import template

from game.services.bet_options import build_match_coupon_options
from tournaments.services.coupons import tournament_rules


register = template.Library()


@register.simple_tag
def coupon_tournament_rules(user):
    """Rules of the live tournaments the capper takes part in, for the tournament choice in the coupon."""
    return tournament_rules(user)


@register.simple_tag
def match_coupon_options(match):
    return build_match_coupon_options(match)
