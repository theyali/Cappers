from django import template

from wallets.package_pricing import format_effective_coin_price_rub
from wallets.services import format_coins, format_money

register = template.Library()


@register.filter
def money(value):
    """Format a monetary value: strip trailing zeros, space as thousands separator."""
    return format_money(value)


@register.filter
def coins(value):
    """Format a coin amount with spaces as thousands separator."""
    return format_coins(value)


@register.filter
def coin_package_rate(package):
    """Format the effective RUB price of one coin for a package."""
    if package is None:
        return "0"
    return format_effective_coin_price_rub(
        getattr(package, "price_rub", 0),
        getattr(package, "total_coins", 0),
    )
