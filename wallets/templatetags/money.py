from django import template

from wallets.services import format_money

register = template.Library()


@register.filter
def money(value):
    """Format a monetary value: strip trailing zeros, space as thousands separator."""
    return format_money(value)
