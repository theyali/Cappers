from django import template

from game.services.bet_options import build_match_coupon_options


register = template.Library()


@register.simple_tag
def match_coupon_options(match):
    return build_match_coupon_options(match)
