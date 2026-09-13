from decimal import Decimal, InvalidOperation
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import CoinSettings, CoinTransaction, CoinWallet


class InsufficientCoins(ValidationError):
    pass


def ensure_coin_wallet(user) -> CoinWallet:
    """Create/lock a user's coin wallet and apply the initial grant exactly once."""
    with transaction.atomic():
        wallet = _coin_wallet_for_update(user)
        _ensure_initial_grant_locked(wallet)
        return wallet


def credit_coins(
    user,
    amount,
    kind: str,
    *,
    related_obj: Any | None = None,
    note: str = "",
) -> CoinWallet:
    amount = _coins(amount)
    if amount <= 0:
        raise ValidationError("Количество коинов для начисления должно быть больше нуля.")
    _validate_kind(kind)
    related_model, related_id = _related_subject(related_obj)

    with transaction.atomic():
        _require_coin_system_enabled()
        wallet = _coin_wallet_for_update(user)
        _ensure_initial_grant_locked(wallet)
        if _has_coin_transaction(user, kind, related_model, related_id):
            return wallet
        return _apply_coin_delta_locked(
            wallet,
            amount,
            kind,
            related_model=related_model,
            related_id=related_id,
            note=note,
        )


def debit_coins(
    user,
    amount,
    kind: str,
    *,
    related_obj: Any | None = None,
    note: str = "",
) -> CoinWallet:
    amount = _coins(amount)
    if amount <= 0:
        raise ValidationError("Количество коинов для списания должно быть больше нуля.")
    _validate_kind(kind)
    related_model, related_id = _related_subject(related_obj)

    with transaction.atomic():
        _require_coin_system_enabled()
        wallet = _coin_wallet_for_update(user)
        _ensure_initial_grant_locked(wallet)
        if _has_coin_transaction(user, kind, related_model, related_id):
            return wallet
        return _apply_coin_delta_locked(
            wallet,
            -amount,
            kind,
            related_model=related_model,
            related_id=related_id,
            note=note,
        )


def adjust_coin_balance(user, amount, *, note: str = "") -> CoinWallet:
    """Safely adjust coins while preserving the ledger; intended for admin use."""
    amount = _coins(amount)
    if amount == 0:
        raise ValidationError("Корректировка коинов не может быть нулевой.")

    with transaction.atomic():
        wallet = _coin_wallet_for_update(user)
        _ensure_initial_grant_locked(wallet)
        return _apply_coin_delta_locked(
            wallet,
            amount,
            CoinTransaction.Kind.ADJUSTMENT,
            note=note or "Ручная корректировка коинов",
        )


def _coin_wallet_for_update(user) -> CoinWallet:
    locked_user = user.__class__.objects.select_for_update().get(pk=user.pk)
    wallet, _ = CoinWallet.objects.get_or_create(user=locked_user)
    return CoinWallet.objects.select_for_update().get(pk=wallet.pk)


def _ensure_initial_grant_locked(wallet: CoinWallet) -> None:
    if CoinTransaction.objects.filter(
        user=wallet.user,
        kind=CoinTransaction.Kind.INITIAL_GRANT,
    ).exists():
        return

    coin_settings = CoinSettings.load()
    if not coin_settings.is_enabled:
        return

    amount = _coins(coin_settings.initial_grant)
    _apply_coin_delta_locked(
        wallet,
        amount,
        CoinTransaction.Kind.INITIAL_GRANT,
        note="Стартовые коины",
    )


def _apply_coin_delta_locked(
    wallet: CoinWallet,
    amount: int,
    kind: str,
    *,
    related_model: str = "",
    related_id: int | None = None,
    note: str = "",
) -> CoinWallet:
    new_balance = int(wallet.balance) + int(amount)
    if new_balance < 0:
        raise InsufficientCoins(
            f"Недостаточно коинов. Доступно {wallet.balance}, нужно {abs(amount)}."
        )

    wallet.balance = new_balance
    wallet.save(update_fields=["balance", "updated_at"])
    CoinTransaction.objects.create(
        user=wallet.user,
        kind=kind,
        amount=amount,
        balance_after=new_balance,
        related_model=related_model,
        related_id=related_id,
        note=note,
    )
    return wallet


def _has_coin_transaction(user, kind: str, related_model: str, related_id: int | None) -> bool:
    if related_id is None:
        return False
    return CoinTransaction.objects.filter(
        user=user,
        kind=kind,
        related_model=related_model,
        related_id=related_id,
    ).exists()


def _related_subject(obj: Any | None) -> tuple[str, int | None]:
    if obj is None:
        return "", None
    pk = getattr(obj, "pk", None)
    if pk is None:
        raise ValidationError("Связанный объект должен быть сохранен до операции с коинами.")
    return obj._meta.label_lower, int(pk)


def _require_coin_system_enabled() -> CoinSettings:
    coin_settings = CoinSettings.load()
    if not coin_settings.is_enabled:
        raise ValidationError("Система коинов временно отключена.")
    return coin_settings


def _validate_kind(kind: str) -> None:
    if kind not in CoinTransaction.Kind.values:
        raise ValidationError("Неизвестный тип coin-транзакции.")


def _coins(value) -> int:
    if isinstance(value, bool):
        raise ValidationError("Количество коинов должно быть целым числом.")
    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError("Количество коинов должно быть целым числом.") from exc
    if not numeric.is_finite() or numeric != numeric.to_integral_value():
        raise ValidationError("Количество коинов должно быть целым числом.")
    return int(numeric)
