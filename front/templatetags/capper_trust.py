from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django import template


register = template.Library()
TRUST_STEP = Decimal("0.1")


@register.inclusion_tag("front/includes/_capper_trust_badge.html")
def capper_trust_badge(value):
    trust_index = _decimal(value)
    trust_index = trust_index.quantize(TRUST_STEP, rounding=ROUND_HALF_UP)
    return {
        "trust_index": trust_index,
        "trust_display": f"{trust_index:.1f}",
        "trust_level": _trust_level(trust_index),
    }


def _decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _trust_level(value: Decimal) -> str:
    if value >= Decimal("8.5"):
        return "high"
    if value >= Decimal("7.0"):
        return "good"
    if value >= Decimal("5.0"):
        return "medium"
    if value > Decimal("0"):
        return "low"
    return "none"
