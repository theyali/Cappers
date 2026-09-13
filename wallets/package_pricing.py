from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


PACKAGE_COIN_PRICE_QUANT = Decimal("0.0001")
ZERO_PACKAGE_COIN_PRICE = Decimal("0.0000")


def effective_coin_price_rub(price_rub, total_coins) -> Decimal:
    """Return the actual RUB price of one coin for a concrete package."""
    try:
        price = Decimal(str(price_rub))
        coin_count = int(total_coins)
    except (InvalidOperation, TypeError, ValueError):
        return ZERO_PACKAGE_COIN_PRICE

    if not price.is_finite() or price <= 0 or coin_count <= 0:
        return ZERO_PACKAGE_COIN_PRICE

    return (price / Decimal(coin_count)).quantize(
        PACKAGE_COIN_PRICE_QUANT,
        rounding=ROUND_HALF_UP,
    )


def format_effective_coin_price_rub(price_rub, total_coins) -> str:
    value = effective_coin_price_rub(price_rub, total_coins)
    text = format(value, "f").rstrip("0").rstrip(".")
    return text or "0"
