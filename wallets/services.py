from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from .models import BalanceTransaction, CapperBalance


MONEY_QUANT = Decimal("0.01")
DEFAULT_CAPPER_STARTING_BALANCE = Decimal("10000.00")
DEFAULT_VIRTUAL_TOP_UP_AMOUNT = Decimal("10000.00")


class InsufficientBalance(Exception):
    pass


def starting_balance() -> Decimal:
    raw = getattr(settings, "CAPPER_STARTING_BALANCE", DEFAULT_CAPPER_STARTING_BALANCE)
    return _money(raw)


def virtual_top_up_amount() -> Decimal:
    raw = getattr(settings, "CAPPER_VIRTUAL_TOP_UP_AMOUNT", DEFAULT_VIRTUAL_TOP_UP_AMOUNT)
    return _money(raw)


def format_money(value) -> str:
    amount = _money(value)
    if amount == amount.to_integral():
        return f"{int(amount):,}".replace(",", " ")
    return f"{amount:,.2f}".replace(",", " ")


def ensure_capper_balance(user) -> CapperBalance:
    with transaction.atomic():
        balance = _balance_for_update(user)
        _ensure_initial_bonus_locked(balance)
        return balance


def top_up_virtual_balance(user, amount, *, note: str = "") -> CapperBalance:
    amount = _money(amount)
    if amount <= 0:
        raise ValidationError("Сумма пополнения должна быть больше нуля.")
    with transaction.atomic():
        balance = _balance_for_update(user)
        _ensure_initial_bonus_locked(balance)
        return _apply_locked(
            balance,
            amount,
            BalanceTransaction.Kind.VIRTUAL_DEPOSIT,
            note=note or "Виртуальное пополнение баланса",
        )


def charge_prediction_stake(user, coupon, amount) -> CapperBalance:
    amount = _money(amount)
    if amount <= 0:
        return ensure_capper_balance(user)

    related_model, related_id = _related_subject(coupon)
    with transaction.atomic():
        balance = _balance_for_update(user)
        _ensure_initial_bonus_locked(balance)
        if _has_transaction(
            user,
            BalanceTransaction.Kind.PREDICTION_STAKE,
            related_model,
            related_id,
        ):
            return balance
        if balance.balance < amount:
            raise InsufficientBalance(
                f"Недостаточно средств на балансе. Доступно {balance.balance} ₽, нужно {amount} ₽."
            )
        return _apply_locked(
            balance,
            -amount,
            BalanceTransaction.Kind.PREDICTION_STAKE,
            related_model=related_model,
            related_id=related_id,
            note=f"Публикация прогноза #{related_id}",
        )


def settle_prediction_coupon(coupon) -> CapperBalance | None:
    from game.models import PredictionCoupon

    if coupon.published_status != PredictionCoupon.PublishedStatus.PUBLISHED:
        return None
    if coupon.state_status == PredictionCoupon.StateStatus.PENDING:
        return None

    related_model, related_id = _related_subject(coupon)
    if not _has_transaction(
        coupon.author,
        BalanceTransaction.Kind.PREDICTION_STAKE,
        related_model,
        related_id,
    ):
        return None

    if coupon.state_status == PredictionCoupon.StateStatus.WIN:
        kind = BalanceTransaction.Kind.PREDICTION_PAYOUT
        amount = _money(coupon.possible_payout)
        note = f"Выплата по прогнозу #{coupon.pk}"
    elif coupon.state_status == PredictionCoupon.StateStatus.REFUND:
        kind = BalanceTransaction.Kind.PREDICTION_REFUND
        amount = _money(coupon.total_stake)
        note = f"Возврат по прогнозу #{coupon.pk}"
    else:
        return None

    if amount <= 0:
        return None

    with transaction.atomic():
        balance = _balance_for_update(coupon.author)
        _ensure_initial_bonus_locked(balance)
        if _has_transaction(coupon.author, kind, related_model, related_id):
            return balance
        return _apply_locked(
            balance,
            amount,
            kind,
            related_model=related_model,
            related_id=related_id,
            note=note,
        )


def _balance_for_update(user) -> CapperBalance:
    balance = CapperBalance.objects.select_for_update().filter(user=user).first()
    if balance is not None:
        return balance
    try:
        return CapperBalance.objects.create(user=user, balance=Decimal("0.00"))
    except IntegrityError:
        return CapperBalance.objects.select_for_update().get(user=user)


def _ensure_initial_bonus_locked(balance: CapperBalance) -> None:
    if BalanceTransaction.objects.filter(
        user=balance.user,
        kind=BalanceTransaction.Kind.INITIAL_BONUS,
    ).exists():
        return
    _apply_locked(
        balance,
        starting_balance(),
        BalanceTransaction.Kind.INITIAL_BONUS,
        note="Стартовый виртуальный баланс каппера",
    )


def _apply_locked(
    balance: CapperBalance,
    amount: Decimal,
    kind: str,
    *,
    related_model: str = "",
    related_id: int | None = None,
    note: str = "",
) -> CapperBalance:
    amount = _money(amount)
    balance.balance = _money(balance.balance + amount)
    balance.save(update_fields=["balance", "updated_at"])
    BalanceTransaction.objects.create(
        user=balance.user,
        kind=kind,
        amount=amount,
        balance_after=balance.balance,
        related_model=related_model,
        related_id=related_id,
        note=note[:255],
    )
    return balance


def _has_transaction(user, kind: str, related_model: str, related_id: int | None) -> bool:
    if related_id is None:
        return False
    return BalanceTransaction.objects.filter(
        user=user,
        kind=kind,
        related_model=related_model,
        related_id=related_id,
    ).exists()


def _related_subject(obj: Any) -> tuple[str, int | None]:
    model = getattr(getattr(obj, "_meta", None), "label_lower", obj.__class__.__name__.lower())
    return str(model), getattr(obj, "pk", None)


def _money(value) -> Decimal:
    return Decimal(str(value or "0")).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)
