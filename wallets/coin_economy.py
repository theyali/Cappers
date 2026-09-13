from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR

from django.core.exceptions import ValidationError

from .models import CoinSettings


RUB_QUANT = Decimal("0.01")
COIN_QUANT = Decimal("1")


def get_coin_price_rub() -> Decimal:
    """Return the configured base price of one coin in rubles."""
    return _resolve_coin_price(None)


def rub_to_coins(rub_amount, *, coin_price_rub=None) -> int:
    """Convert rubles to whole coins, rounding up for a debit/stake amount."""
    amount = _decimal_amount(rub_amount, field_name="Сумма в рублях")
    if amount < 0:
        raise ValidationError("Сумма в рублях не может быть отрицательной.")

    price = _resolve_coin_price(coin_price_rub)
    return int((amount / price).quantize(COIN_QUANT, rounding=ROUND_CEILING))


def coins_to_rub(coins, *, coin_price_rub=None) -> Decimal:
    """Return a display-only ruble equivalent, rounded down to kopecks."""
    amount = _decimal_amount(coins, field_name="Количество коинов")
    if amount < 0:
        raise ValidationError("Количество коинов не может быть отрицательным.")
    if amount != amount.to_integral_value():
        raise ValidationError("Количество коинов должно быть целым числом.")

    price = _resolve_coin_price(coin_price_rub)
    return (amount * price).quantize(RUB_QUANT, rounding=ROUND_FLOOR)


def _resolve_coin_price(coin_price_rub) -> Decimal:
    raw_price = CoinSettings.load().coin_price_rub if coin_price_rub is None else coin_price_rub
    price = _decimal_amount(raw_price, field_name="Цена коина")
    if price <= 0:
        raise ValidationError("Цена одного коина должна быть больше нуля.")
    return price


def _decimal_amount(value, *, field_name: str) -> Decimal:
    if isinstance(value, bool):
        raise ValidationError(f"{field_name}: некорректное значение.")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(f"{field_name}: некорректное значение.") from exc
    if not amount.is_finite():
        raise ValidationError(f"{field_name}: некорректное значение.")
    return amount
