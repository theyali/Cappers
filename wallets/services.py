import logging
from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any
from types import SimpleNamespace

from django.conf import settings
from zoneinfo import ZoneInfo
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import F, Q, Sum
from django.utils import timezone
from django.urls import reverse

from back.models import WebsiteSettings
from cabinet.models import User

from .models import (
    CapperRealBalance,
    CoinPackage,
    CoinSettings,
    CoinTransaction,
    CoinWallet,
    CopiedBet,
    CopyBettingSubscription,
    CopyBettingBlock, CopyBettingLimits,
    RealBalanceTransaction,
)


MONEY_QUANT = Decimal("0.01")
logger = logging.getLogger(__name__)

# Coins credited for a settled bet: the first payout or refund and later corrections.
PREDICTION_SETTLEMENT_KINDS = (
    CoinTransaction.Kind.PREDICTION_PAYOUT,
    CoinTransaction.Kind.PREDICTION_REFUND,
    CoinTransaction.Kind.PREDICTION_PAYOUT_REVERSAL,
)
COPYBET_SETTLEMENT_KINDS = (
    CoinTransaction.Kind.COPYBET_PAYOUT,
    CoinTransaction.Kind.COPYBET_REFUND,
    CoinTransaction.Kind.COPYBET_PAYOUT_REVERSAL,
)
# Income that comes from a user's payment can be disputed, so it is held before withdrawal.
HELD_INCOME_KINDS = (
    RealBalanceTransaction.Kind.SUBSCRIPTION_INCOME,
    RealBalanceTransaction.Kind.REFERRAL_SUBSCRIPTION,
    RealBalanceTransaction.Kind.REFERRAL_BALANCE_TOP_UP,
)


class InsufficientBalance(Exception):
    """Insufficient real-money balance."""


class InsufficientCoins(ValidationError):
    """Insufficient application coins."""


def format_money(value) -> str:
    amount = _money(value)
    if amount == amount.to_integral():
        return f"{int(amount):,}".replace(",", " ")
    return f"{amount:,.2f}".replace(",", " ")


def format_coins(value) -> str:
    amount = _coin_int(value)
    return f"{amount:,}".replace(",", " ")


def ensure_coin_wallet(user) -> CoinWallet:
    """Create and lock a coin wallet, granting configured starting coins once."""
    with transaction.atomic():
        wallet = _coin_wallet_for_update(user)
        _ensure_initial_coin_grant_locked(wallet)
        return wallet


def credit_coins(
    user,
    amount: int,
    kind: str,
    related_obj=None,
    note: str = "",
) -> CoinWallet:
    amount = _coin_int(amount)
    if amount <= 0:
        raise ValidationError("Количество коинов для начисления должно быть больше нуля.")
    _validate_coin_kind(kind)
    related_model, related_id = _coin_related_subject(related_obj)

    with transaction.atomic():
        _require_coin_system_enabled()
        wallet = _coin_wallet_for_update(user)
        _ensure_initial_coin_grant_locked(wallet)
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


def charge_coins(
    user,
    amount: int,
    kind: str,
    related_obj=None,
    note: str = "",
) -> CoinWallet:
    amount = _coin_int(amount)
    if amount <= 0:
        raise ValidationError("Количество коинов для списания должно быть больше нуля.")
    _validate_coin_kind(kind)
    related_model, related_id = _coin_related_subject(related_obj)

    with transaction.atomic():
        _require_coin_system_enabled()
        wallet = _coin_wallet_for_update(user)
        _ensure_initial_coin_grant_locked(wallet)
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


def purchase_coin_package(
    user,
    package: CoinPackage,
    payment=None,
    note: str = "",
) -> CoinWallet:
    """Credit a coin package.

    Without ``payment`` this is a purchase at checkout: only an active package can
    be bought, on its current terms. With ``payment`` the money is already taken,
    so ``package`` is the snapshot the user paid for and is credited as is, even
    if the package was disabled or edited after the payment.
    """
    if not package or not getattr(package, "pk", None):
        raise ValidationError("Пакет коинов не найден.")

    with transaction.atomic():
        current_package = package
        if payment is None:
            current_package = CoinPackage.objects.get(pk=package.pk)
            if not current_package.is_active:
                raise ValidationError("Этот пакет коинов больше недоступен.")

        latest_purchase_id = (
            CoinTransaction.objects.filter(
                user=user,
                kind=CoinTransaction.Kind.PACKAGE_PURCHASE,
            )
            .order_by("-id")
            .values_list("id", flat=True)
            .first()
            or 0
        )
        wallet = credit_coins(
            user,
            int(current_package.total_coins),
            CoinTransaction.Kind.PACKAGE_PURCHASE,
            related_obj=payment,
            note=note or f"Покупка пакета «{current_package.title}»",
        )

        purchase_transaction = None
        if payment is not None and getattr(payment, "pk", None):
            purchase_transaction = (
                CoinTransaction.objects.filter(
                    user=user,
                    kind=CoinTransaction.Kind.PACKAGE_PURCHASE,
                    related_model=payment._meta.label_lower,
                    related_id=payment.pk,
                )
                .order_by("-id")
                .first()
            )
        if purchase_transaction is None:
            purchase_transaction = (
                CoinTransaction.objects.filter(
                    user=user,
                    kind=CoinTransaction.Kind.PACKAGE_PURCHASE,
                    id__gt=latest_purchase_id,
                )
                .order_by("-id")
                .first()
            )

        from cabinet.referrals import (
            REFERRAL_ACTION_BALANCE_TOP_UP,
            credit_referral_income,
        )
        from cabinet.services.referral_bonuses import (
            grant_referral_first_topup_bonus,
        )

        grant_referral_first_topup_bonus(
            user,
            current_package.price_rub,
            related_obj=purchase_transaction,
        )
        credit_referral_income(
            user,
            current_package.price_rub,
            REFERRAL_ACTION_BALANCE_TOP_UP,
            related_obj=purchase_transaction,
            note=f"Реферал @{user.username}: пополнение через «{current_package.title}»",
        )
        return wallet


def adjust_coin_balance(user, amount: int, *, note: str = "") -> CoinWallet:
    amount = _coin_int(amount)
    if amount == 0:
        raise ValidationError("Корректировка коинов не может быть нулевой.")

    with transaction.atomic():
        wallet = _coin_wallet_for_update(user)
        _ensure_initial_coin_grant_locked(wallet)
        return _apply_coin_delta_locked(
            wallet,
            amount,
            CoinTransaction.Kind.ADJUSTMENT,
            note=note or "Ручная корректировка коинов",
        )


def ensure_real_balance(user) -> CapperRealBalance:
    _validate_real_balance_user(user)
    with transaction.atomic():
        return _real_balance_for_update(user)


def debit_real_balance(
    user,
    amount,
    kind: str,
    *,
    related_obj: Any | None = None,
    note: str = "",
) -> CapperRealBalance:
    _validate_real_balance_user(user)
    amount = _money(amount)
    if amount <= 0:
        raise ValidationError("Сумма списания должна быть больше нуля.")
    related_model, related_id = _related_subject(related_obj) if related_obj is not None else ("", None)

    with transaction.atomic():
        balance = _real_balance_for_update(user)
        if _has_real_transaction(user, kind, related_model, related_id):
            return balance
        if balance.balance < amount:
            raise InsufficientBalance(
                f"Недостаточно средств на реальном балансе. Доступно {balance.balance} ₽, нужно {amount} ₽."
            )
        return _apply_real_locked(
            balance,
            -amount,
            kind,
            related_model=related_model,
            related_id=related_id,
            note=note,
        )


def credit_real_balance(
    user,
    amount,
    kind: str,
    *,
    related_obj: Any | None = None,
    note: str = "",
    hold_days: int | None = None,
) -> CapperRealBalance:
    _validate_analyst(user)
    amount = _money(amount)
    if amount <= 0:
        raise ValidationError("Сумма зачисления должна быть больше нуля.")
    related_model, related_id = _related_subject(related_obj) if related_obj is not None else ("", None)

    if hold_days is None:
        hold_days = WebsiteSettings.load().income_hold_days if kind in HELD_INCOME_KINDS else 0

    with transaction.atomic():
        balance = _real_balance_for_update(user)
        if _has_real_transaction(user, kind, related_model, related_id):
            return balance
        if hold_days:
            balance.held = _money(balance.held + amount)
            balance.save(update_fields=["held", "updated_at"])
            RealBalanceTransaction.objects.create(
                user=user,
                kind=kind,
                status=RealBalanceTransaction.Status.HELD,
                amount=amount,
                balance_after=balance.balance,
                related_model=related_model,
                related_id=related_id,
                available_at=timezone.now() + timedelta(days=hold_days),
                note=note[:255],
            )
            return balance
        return _apply_real_locked(
            balance,
            amount,
            kind,
            related_model=related_model,
            related_id=related_id,
            note=note,
        )


def reverse_paid_coupon_money(purchase, *, refund_to_balance):
    """Reverse saved amounts, including held/spent income; caller locks the purchase."""
    with transaction.atomic():
        wallets = {user_id: _real_balance_for_update(user) for user_id, user in sorted(
            [(purchase.buyer_id, purchase.buyer), (purchase.analyst_id, purchase.analyst)]
        )}
        model, pk = _related_subject(purchase)
        if refund_to_balance and not _has_real_transaction(purchase.buyer, RealBalanceTransaction.Kind.COUPON_REFUND, model, pk):
            _apply_real_locked(wallets[purchase.buyer_id], purchase.price,
                RealBalanceTransaction.Kind.COUPON_REFUND, related_model=model, related_id=pk)
        if purchase.capper_income and not _has_real_transaction(purchase.analyst, RealBalanceTransaction.Kind.COUPON_INCOME_REVERSAL, model, pk):
            original = RealBalanceTransaction.objects.select_for_update().get(
                user=purchase.analyst, kind=RealBalanceTransaction.Kind.COUPON_INCOME,
                related_model=model, related_id=pk,
            )
            wallet = wallets[purchase.analyst_id]
            if original.status == RealBalanceTransaction.Status.HELD:
                wallet.held = _money(wallet.held - purchase.capper_income)
                wallet.save(update_fields=["held", "updated_at"])
                original.status = RealBalanceTransaction.Status.CANCELED
                original.save(update_fields=["status"])
                RealBalanceTransaction.objects.create(user=purchase.analyst,
                    kind=RealBalanceTransaction.Kind.COUPON_INCOME_REVERSAL, amount=-purchase.capper_income,
                    status=RealBalanceTransaction.Status.CANCELED, balance_after=wallet.balance, related_model=model, related_id=pk)
            else:
                # A negative balance records the debt when the author already withdrew it.
                _apply_real_locked(wallet, -purchase.capper_income,
                    RealBalanceTransaction.Kind.COUPON_INCOME_REVERSAL, related_model=model, related_id=pk)


def release_held_real_income(limit: int = 1000) -> int:
    """Move income whose hold is over to the available balance."""
    held_ids = list(
        RealBalanceTransaction.objects.filter(
            status=RealBalanceTransaction.Status.HELD,
            available_at__lte=timezone.now(),
        )
        .order_by("available_at", "id")
        .values_list("pk", flat=True)[:limit]
    )
    released = 0
    for held_id in held_ids:
        with transaction.atomic():
            held = RealBalanceTransaction.objects.select_related("user").get(pk=held_id)
            balance = _real_balance_for_update(held.user)
            held = RealBalanceTransaction.objects.select_for_update().get(pk=held_id)
            if held.status != RealBalanceTransaction.Status.HELD:
                continue
            balance.held = max(Decimal("0.00"), _money(balance.held - held.amount))
            balance.balance = _money(balance.balance + held.amount)
            balance.save(update_fields=["balance", "held", "updated_at"])
            held.status = RealBalanceTransaction.Status.COMPLETED
            held.balance_after = balance.balance
            held.save(update_fields=["status", "balance_after"])
        released += 1
    return released


def request_real_withdrawal(
    user,
    amount,
    *,
    payout_details: str = "",
    note: str = "",
) -> CapperRealBalance:
    _validate_analyst(user)
    amount = _money(amount)
    if amount <= 0:
        raise ValidationError("Сумма вывода должна быть больше нуля.")
    config = WebsiteSettings.load()
    min_amount = _money(config.min_withdrawal_amount)
    if amount < min_amount:
        raise ValidationError(f"Минимальная сумма вывода — {format_money(min_amount)} ₽.")
    payout_details = (payout_details or "").strip()
    if not payout_details:
        raise ValidationError("Укажите реквизиты для вывода.")

    with transaction.atomic():
        balance = _real_balance_for_update(user)
        if RealBalanceTransaction.objects.filter(
            user=user,
            kind=RealBalanceTransaction.Kind.WITHDRAWAL_REQUEST,
            status=RealBalanceTransaction.Status.PENDING,
        ).exists():
            raise ValidationError("У вас уже есть заявка на вывод. Дождитесь её обработки.")
        local_now = timezone.now().astimezone(ZoneInfo(settings.TIME_ZONE))
        week_start = (local_now - timedelta(days=local_now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        requests_count = RealBalanceTransaction.objects.filter(
            user=user, kind=RealBalanceTransaction.Kind.WITHDRAWAL_REQUEST,
            status__in=[RealBalanceTransaction.Status.PENDING, RealBalanceTransaction.Status.COMPLETED],
            created_at__gte=week_start,
        ).count()
        if requests_count >= config.withdrawal_requests_per_week:
            raise ValidationError(f"Можно создать не более {config.withdrawal_requests_per_week} заявок на вывод за неделю.")
        if balance.balance < amount:
            raise InsufficientBalance(
                f"Недостаточно средств на реальном балансе. Доступно {balance.balance} ₽, нужно {amount} ₽."
            )
        balance.pending_withdrawal = max(
            Decimal("0.00"),
            _money(balance.pending_withdrawal + amount),
        )
        balance.save(update_fields=["pending_withdrawal", "updated_at"])
        _apply_real_locked(
            balance,
            -amount,
            RealBalanceTransaction.Kind.WITHDRAWAL_REQUEST,
            status=RealBalanceTransaction.Status.PENDING,
            note=note or "Заявка на вывод средств",
            payout_details=payout_details,
        )
        return balance


def approve_real_withdrawal(
    withdrawal: RealBalanceTransaction,
    *,
    payout_reference: str = "",
    processed_by=None,
) -> RealBalanceTransaction:
    with transaction.atomic():
        locked = RealBalanceTransaction.objects.select_for_update().get(pk=withdrawal.pk)
        _validate_pending_withdrawal_transaction(locked)
        payout_reference = (payout_reference or locked.payout_reference).strip()
        if not payout_reference:
            raise ValidationError("Укажите номер выплаты.")
        balance = _real_balance_for_update(locked.user)
        balance.pending_withdrawal = max(
            Decimal("0.00"),
            _money(balance.pending_withdrawal - abs(locked.amount)),
        )
        balance.save(update_fields=["pending_withdrawal", "updated_at"])
        locked.status = RealBalanceTransaction.Status.COMPLETED
        locked.payout_reference = payout_reference[:100]
        locked.processed_by = processed_by
        locked.processed_at = timezone.now()
        locked.save(update_fields=["status", "payout_reference", "processed_by", "processed_at"])
        return locked


def cancel_real_withdrawal(withdrawal: RealBalanceTransaction, *, processed_by=None) -> RealBalanceTransaction:
    with transaction.atomic():
        locked = RealBalanceTransaction.objects.select_for_update().get(pk=withdrawal.pk)
        _validate_pending_withdrawal_transaction(locked)
        balance = _real_balance_for_update(locked.user)
        refund_amount = abs(locked.amount)
        balance.pending_withdrawal = max(
            Decimal("0.00"),
            _money(balance.pending_withdrawal - refund_amount),
        )
        balance.save(update_fields=["pending_withdrawal", "updated_at"])
        locked.status = RealBalanceTransaction.Status.CANCELED
        locked.processed_by = processed_by
        locked.processed_at = timezone.now()
        locked.save(update_fields=["status", "processed_by", "processed_at"])
        related_model, related_id = _related_subject(locked)
        if not _has_real_transaction(
            locked.user,
            RealBalanceTransaction.Kind.WITHDRAWAL_CANCEL,
            related_model,
            related_id,
        ):
            _apply_real_locked(
                balance,
                refund_amount,
                RealBalanceTransaction.Kind.WITHDRAWAL_CANCEL,
                related_model=related_model,
                related_id=related_id,
                note=f"Отмена заявки на вывод #{locked.pk}",
            )
        return locked


def charge_prediction_stake(user, coupon, amount) -> CoinWallet:
    coin_amount = _coin_amount_from_model(amount, field_name="Ставка")
    if coin_amount <= 0:
        return ensure_coin_wallet(user)
    return charge_coins(
        user,
        coin_amount,
        CoinTransaction.Kind.PREDICTION_STAKE,
        related_obj=coupon,
        note=f"Публикация прогноза #{coupon.pk}",
    )


def cover_prediction_stake_with_free_reward(user, coupon, *, note: str = "") -> CoinWallet:
    """Mark a coupon stake as covered by a free prediction reward.

    Settlement checks whether a PREDICTION_STAKE transaction already exists for
    the coupon. A zero-amount transaction keeps that process idempotent without
    changing the user's coin balance.
    """
    related_model, related_id = _coin_related_subject(coupon)

    with transaction.atomic():
        _require_coin_system_enabled()
        wallet = _coin_wallet_for_update(user)
        _ensure_initial_coin_grant_locked(wallet)
        if _has_coin_transaction(
            user,
            CoinTransaction.Kind.PREDICTION_STAKE,
            related_model,
            related_id,
        ):
            return wallet
        CoinTransaction.objects.create(
            user=user,
            kind=CoinTransaction.Kind.PREDICTION_STAKE,
            amount=0,
            balance_after=wallet.balance,
            related_model=related_model,
            related_id=related_id,
            note=(note or f"Бесплатный прогноз #{coupon.pk}")[:255],
        )
        return wallet


def settle_prediction_coupon(coupon, change=None) -> CoinWallet | None:
    """Bring the author's and followers' coins in line with the coupon result.

    ``change`` is the recorded result change of a resettlement: only with it are
    coins taken back from an earlier settlement.
    """
    from game.models import PredictionCoupon

    if coupon.published_status != PredictionCoupon.PublishedStatus.PUBLISHED:
        return None
    if coupon.state_status == PredictionCoupon.StateStatus.PENDING and change is None:
        return None

    wallet = ensure_coin_wallet(coupon.author)
    stake_amount = _coin_amount_from_model(coupon.total_stake, field_name="Ставка")
    stake_related_model, stake_related_id = _coin_related_subject(coupon)
    if stake_amount > 0 and coupon.state_status != PredictionCoupon.StateStatus.PENDING:
        # Coupons are charged on publish. Older coupons and bot coupons may still
        # be unpaid: charge them now, but never let a missing balance roll back
        # the settlement itself — such a coupon is settled without coin movements.
        try:
            wallet = charge_coins(
                coupon.author,
                stake_amount,
                CoinTransaction.Kind.PREDICTION_STAKE,
                related_obj=coupon,
                note=f"Списание ставки по рассчитанному прогнозу #{coupon.pk}",
            )
        except InsufficientCoins:
            logger.warning(
                "Coupon #%s settled without coin movements: stake %s was not charged on publish "
                "and the author has not enough coins.",
                coupon.pk,
                stake_amount,
            )
            _copy_missing_bets_for_settlement(coupon)
            settle_copied_bets_for_coupon(coupon, change=change)
            return wallet
    stake_transaction = (
        CoinTransaction.objects.filter(
            user=coupon.author,
            kind=CoinTransaction.Kind.PREDICTION_STAKE,
            related_model=stake_related_model,
            related_id=stake_related_id,
        )
        .order_by("id")
        .first()
    )
    refundable_stake = (
        abs(stake_transaction.amount)
        if stake_transaction and stake_transaction.amount < 0
        else 0
    )

    if coupon.state_status == PredictionCoupon.StateStatus.WIN:
        target = _rounded_coin_amount(coupon.possible_payout)
        credit_kind = CoinTransaction.Kind.PREDICTION_PAYOUT
        note = f"Выплата по прогнозу #{coupon.pk}"
    elif coupon.state_status == PredictionCoupon.StateStatus.REFUND:
        target = refundable_stake
        credit_kind = CoinTransaction.Kind.PREDICTION_REFUND
        note = f"Возврат по прогнозу #{coupon.pk}"
    else:
        target = 0
        credit_kind = CoinTransaction.Kind.PREDICTION_PAYOUT
        note = f"Выплата по прогнозу #{coupon.pk}"
    settled_wallet, moved, uncollected = _settle_coins_to_target(
        coupon.author,
        target,
        credit_kind=credit_kind,
        reversal_kind=CoinTransaction.Kind.PREDICTION_PAYOUT_REVERSAL,
        settlement_kinds=PREDICTION_SETTLEMENT_KINDS,
        subject=coupon,
        change=change,
        change_subjects=_result_change_subjects(coupon),
        note=note,
        reversal_note=f"Сторно по перерасчёту прогноза #{coupon.pk}",
    )
    if change is not None and (moved or uncollected):
        type(change).objects.filter(pk=change.pk).update(
            author_coins=moved,
            uncollected_coins=F("uncollected_coins") + uncollected,
        )

    _copy_missing_bets_for_settlement(coupon)
    settle_copied_bets_for_coupon(coupon, change=change)
    return settled_wallet or wallet


def _result_change_subjects(coupon) -> Q:
    """Transactions linked to the coupon's result changes, i.e. resettlement corrections."""
    changes = coupon.result_changes.all()
    return Q(related_model=changes.model._meta.label_lower, related_id__in=changes.values("pk"))


def _settle_coins_to_target(
    user,
    target: int,
    *,
    credit_kind: str,
    reversal_kind: str,
    settlement_kinds: tuple[str, ...],
    subject,
    change,
    change_subjects: Q,
    note: str,
    reversal_note: str,
) -> tuple[CoinWallet | None, int, int]:
    """Make the coins credited for a settled bet equal ``target``.

    Returns the wallet, the coins moved and the coins that could not be taken
    back. The first payout or refund is linked to the bet itself, as before.
    Later corrections are linked to the coupon result change, so a coupon can be
    resettled any number of times without hitting the idempotency key. Coins
    are taken back only as part of a recorded result change, and never below
    a zero balance: the rest is reported as uncollected.
    """
    if change is None and target <= 0:
        return None, 0, 0
    related_model, related_id = _coin_related_subject(subject)

    with transaction.atomic():
        wallet = _coin_wallet_for_update(user)
        credited = (
            CoinTransaction.objects.filter(
                Q(related_model=related_model, related_id=related_id) | change_subjects,
                user=user,
                kind__in=settlement_kinds,
            ).aggregate(total=Sum("amount"))["total"]
            or 0
        )
        delta = target - credited
        if delta == 0:
            return wallet, 0, 0

        _require_coin_system_enabled()
        _ensure_initial_coin_grant_locked(wallet)
        kind = credit_kind if delta > 0 else reversal_kind
        if delta < 0 or _has_coin_transaction(user, kind, related_model, related_id):
            if change is None:
                return wallet, 0, 0
            related_model, related_id = _coin_related_subject(change)
            note = f"Перерасчёт: {note}" if delta > 0 else reversal_note

        uncollected = 0
        if delta < 0 and wallet.balance < -delta:
            uncollected = -delta - int(wallet.balance)
            delta = -int(wallet.balance)
            logger.warning(
                "Could not take back %s coins from user #%s for %s #%s: not enough balance.",
                uncollected,
                user.pk,
                subject._meta.label_lower,
                subject.pk,
            )
        if delta:
            wallet = _apply_coin_delta_locked(
                wallet,
                delta,
                kind,
                related_model=related_model,
                related_id=related_id,
                note=note,
            )
        return wallet, delta, uncollected


def activate_copybetting(
    *,
    user,
    analyst,
    bank_amount,
    stake_percent,
    stop_loss_amount=0,
    max_single_stake=0,
    min_total_coefficient=Decimal("1.01"),
    copy_regular_coupons=True,
    copy_tournament_coupons=True,
    allowed_sports=None,
) -> CopyBettingSubscription:
    if not getattr(user, "is_authenticated", False):
        raise PermissionDenied("Войдите, чтобы настроить копирование.")
    if user.pk == analyst.pk:
        raise ValidationError("Нельзя копировать самого себя.")
    if analyst.role != User.Role.ANALYST:
        raise ValidationError("Копировать можно только каппера.")

    bank_amount = _coin_decimal_input(bank_amount, "Банк для копирования")
    stop_loss_amount = _coin_decimal_input(stop_loss_amount, "Стоп-лосс", allow_zero=True)
    max_single_stake = _coin_decimal_input(max_single_stake, "Максимум ставки", allow_zero=True)
    min_total_coefficient = _money(min_total_coefficient)
    stake_percent = _money(stake_percent)
    if bank_amount <= 0:
        raise ValidationError("Укажите банк для копирования.")
    if not Decimal("0.01") <= stake_percent <= Decimal("100.00"):
        raise ValidationError("Процент от банка должен быть от 0.01 до 100.")
    if min_total_coefficient < Decimal("1.01"):
        raise ValidationError("Минимальный коэффициент — 1.01.")
    validate_copybetting_stake(bank_amount=bank_amount, stake_percent=stake_percent, max_single_stake=max_single_stake)
    if not copy_regular_coupons and not copy_tournament_coupons:
        raise ValidationError("Выберите хотя бы один тип прогнозов для копирования.")

    ensure_coin_wallet(user)
    active_since = timezone.now()
    with transaction.atomic():
        User.objects.select_for_update(no_key=True).get(pk=user.pk)
        validate_copybetting_access(user.pk, analyst.pk, activating=True)
        subscription, _ = CopyBettingSubscription.objects.select_for_update().get_or_create(
            user=user,
            analyst=analyst,
            defaults={
                "bank_amount": bank_amount,
                "stake_percent": stake_percent,
                "stop_loss_amount": stop_loss_amount,
                "max_single_stake": max_single_stake,
                "min_total_coefficient": min_total_coefficient,
                "copy_regular_coupons": copy_regular_coupons,
                "copy_tournament_coupons": copy_tournament_coupons,
                "active_since": active_since,
            },
        )
        was_stopped = subscription.status == CopyBettingSubscription.Status.STOPPED
        was_inactive = subscription.status != CopyBettingSubscription.Status.ACTIVE
        had_pending_status = bool(subscription.pending_status)
        subscription.bank_amount = bank_amount
        subscription.stake_percent = stake_percent
        subscription.stop_loss_amount = stop_loss_amount
        subscription.max_single_stake = max_single_stake
        subscription.min_total_coefficient = min_total_coefficient
        subscription.copy_regular_coupons = copy_regular_coupons
        subscription.copy_tournament_coupons = copy_tournament_coupons
        subscription._transition_actor = user
        subscription.status = CopyBettingSubscription.Status.ACTIVE
        subscription.pending_status = ""
        subscription.pending_status_requested_at = None
        subscription.stopped_at = None
        if was_inactive or had_pending_status or not subscription.active_since:
            subscription.active_since = active_since
        if was_stopped:
            subscription.current_loss = Decimal("0")
        subscription.save(
            update_fields=[
                "bank_amount",
                "stake_percent",
                "stop_loss_amount",
                "max_single_stake",
                "min_total_coefficient",
                "copy_regular_coupons",
                "copy_tournament_coupons",
                "status",
                "active_since",
                "pending_status",
                "pending_status_requested_at",
                "stopped_at",
                "current_loss",
                "updated_at",
            ]
        )
        if allowed_sports is not None:
            subscription.allowed_sports.set(allowed_sports)
    return subscription


def pause_copybetting(subscription: CopyBettingSubscription) -> CopyBettingSubscription:
    return _request_copybetting_status(subscription, CopyBettingSubscription.Status.PAUSED)


def resume_copybetting(subscription: CopyBettingSubscription) -> CopyBettingSubscription:
    with transaction.atomic():
        User.objects.select_for_update(no_key=True).get(pk=subscription.user_id)
        validate_copybetting_access(subscription.user_id, subscription.analyst_id, activating=True)
        validate_copybetting_stake(bank_amount=subscription.bank_amount, stake_percent=subscription.stake_percent, max_single_stake=subscription.max_single_stake)
        locked_subscription = CopyBettingSubscription.objects.select_for_update().get(pk=subscription.pk)
        locked_subscription._transition_actor = User(pk=subscription.user_id)
        if locked_subscription.status == CopyBettingSubscription.Status.ACTIVE:
            if locked_subscription.pending_status:
                locked_subscription.pending_status = ""
                locked_subscription.pending_status_requested_at = None
                locked_subscription.active_since = timezone.now()
                locked_subscription.save(
                    update_fields=[
                        "active_since",
                        "pending_status",
                        "pending_status_requested_at",
                        "updated_at",
                    ]
                )
            return locked_subscription

        locked_subscription.status = CopyBettingSubscription.Status.ACTIVE
        locked_subscription.active_since = timezone.now()
        locked_subscription.pending_status = ""
        locked_subscription.pending_status_requested_at = None
        locked_subscription.stopped_at = None
        locked_subscription.save(
            update_fields=[
                "status",
                "active_since",
                "pending_status",
                "pending_status_requested_at",
                "stopped_at",
                "updated_at",
            ]
        )
        return locked_subscription


def stop_copybetting(subscription: CopyBettingSubscription) -> CopyBettingSubscription:
    return _request_copybetting_status(subscription, CopyBettingSubscription.Status.STOPPED)


def _request_copybetting_status(
    subscription: CopyBettingSubscription,
    target_status: str,
) -> CopyBettingSubscription:
    if target_status not in {
        CopyBettingSubscription.Status.PAUSED,
        CopyBettingSubscription.Status.STOPPED,
    }:
        raise ValidationError("Некорректный статус копибеттинга.")

    with transaction.atomic():
        User.objects.select_for_update(no_key=True).get(pk=subscription.user_id)
        validate_copybetting_access(subscription.user_id, subscription.analyst_id)
        locked_subscription = CopyBettingSubscription.objects.select_for_update().get(pk=subscription.pk)
        locked_subscription._transition_actor = User(pk=subscription.user_id)
        if locked_subscription.status == target_status and not locked_subscription.pending_status:
            return locked_subscription

        if _has_started_pending_copied_bets(locked_subscription):
            locked_subscription.pending_status = target_status
            locked_subscription.pending_status_requested_at = timezone.now()
            locked_subscription.save(
                update_fields=[
                    "pending_status",
                    "pending_status_requested_at",
                    "updated_at",
                ]
            )
            return locked_subscription

        _apply_copybetting_status_locked(locked_subscription, target_status)
        return locked_subscription


def _apply_copybetting_status_locked(
    subscription: CopyBettingSubscription,
    target_status: str,
) -> None:
    if subscription.status == CopyBettingSubscription.Status.STOPPED:
        return

    update_fields = [
        "status",
        "pending_status",
        "pending_status_requested_at",
        "updated_at",
    ]

    subscription.status = target_status
    subscription.pending_status = ""
    subscription.pending_status_requested_at = None
    if target_status == CopyBettingSubscription.Status.STOPPED:
        subscription.stopped_at = timezone.now()
        update_fields.append("stopped_at")
    subscription.save(update_fields=update_fields)


def copy_published_coupon(coupon) -> list[CopiedBet]:
    from game.models import PredictionCoupon

    if coupon.published_status != PredictionCoupon.PublishedStatus.PUBLISHED:
        return []
    if coupon.total_stake <= 0:
        return []

    created_bets: list[CopiedBet] = []
    subscriptions = (
        CopyBettingSubscription.objects.filter(
            analyst=coupon.author,
            status=CopyBettingSubscription.Status.ACTIVE,
            pending_status="",
        )
        .exclude(user=coupon.author)
        .select_related("user", "analyst")
        .order_by("id")
    )

    for subscription in subscriptions:
        copied_bet = _copy_coupon_for_subscription(coupon, subscription)
        if copied_bet is not None:
            created_bets.append(copied_bet)

    if coupon.state_status != PredictionCoupon.StateStatus.PENDING:
        settle_copied_bets_for_coupon(coupon)
    return created_bets


def _copy_coupon_for_subscription(
    coupon,
    subscription: CopyBettingSubscription,
    *,
    allow_pending_status: bool = False,
) -> CopiedBet | None:
    from game.models import PredictionCoupon

    if coupon.published_status != PredictionCoupon.PublishedStatus.PUBLISHED:
        return None
    if coupon.total_stake <= 0:
        return None
    if subscription.user_id == coupon.author_id:
        return None

    with transaction.atomic():
        User.objects.select_for_update(no_key=True).get(pk=subscription.user_id)
        if CopyBettingBlock.objects.filter(user_id=subscription.user_id, analyst_id=coupon.author_id, revoked_at__isnull=True).exists():
            return None
        locked_subscription = (
            CopyBettingSubscription.objects.select_for_update(of=("self",))
            .select_related("user", "analyst")
            .get(pk=subscription.pk)
        )
        if locked_subscription.status != CopyBettingSubscription.Status.ACTIVE:
            return None
        if locked_subscription.pending_status and not allow_pending_status:
            return None
        if not _coupon_is_after_active_since(coupon, locked_subscription):
            return None

        stake = _copy_stake(locked_subscription)
        from game.services.coupon_validation import PREDICTION_STAKE_MIN_COINS
        if stake < PREDICTION_STAKE_MIN_COINS:
            return None
        if not copybetting_within_global_limits(locked_subscription.user_id, stake):
            return None
        if not _copybetting_allows_coupon(locked_subscription, coupon):
            return None
        if (
            locked_subscription.stop_loss_amount > 0
            and locked_subscription.current_loss >= locked_subscription.stop_loss_amount
        ):
            _apply_copybetting_status_locked(
                locked_subscription,
                CopyBettingSubscription.Status.STOPPED,
            )
            return None

        copied_bet, created = CopiedBet.objects.get_or_create(
            user=locked_subscription.user,
            source_coupon=coupon,
            defaults={
                "subscription": locked_subscription,
                "analyst": coupon.author,
                "stake": stake,
                "possible_payout": _copy_possible_payout(coupon, stake),
            },
        )
        if not created:
            return None

        try:
            _charge_copied_bet_stake(copied_bet)
        except InsufficientCoins:
            copied_bet.delete()
            return None

        locked_subscription.total_staked = _coin_decimal_total(locked_subscription.total_staked + stake)
        locked_subscription.save(update_fields=["total_staked", "updated_at"])
        subscription.total_staked = locked_subscription.total_staked
        return copied_bet


def _copy_missing_bets_for_settlement(coupon) -> list[CopiedBet]:
    from game.models import PredictionCoupon

    if coupon.state_status == PredictionCoupon.StateStatus.PENDING:
        return []
    published_at = _coupon_published_at(coupon)
    if not coupon.settled_at or not published_at:
        return []

    created: list[CopiedBet] = []
    subscriptions = (
        CopyBettingSubscription.objects.filter(
            analyst=coupon.author,
            status=CopyBettingSubscription.Status.ACTIVE,
            active_since__lte=published_at,
        )
        .exclude(user=coupon.author)
        .exclude(copied_bets__source_coupon=coupon)
        .select_related("user", "analyst")
        .order_by("id")
    )
    for subscription in subscriptions:
        copied_bet = _copy_coupon_for_subscription(
            coupon,
            subscription,
            allow_pending_status=True,
        )
        if copied_bet is not None:
            created.append(copied_bet)
    return created


def _coupon_published_at(coupon):
    return coupon.published_at or coupon.created_at


def _coupon_is_after_active_since(coupon, subscription: CopyBettingSubscription) -> bool:
    published_at = _coupon_published_at(coupon)
    if not published_at:
        return True
    if subscription.active_since and published_at < subscription.active_since:
        return False
    if (
        subscription.pending_status
        and subscription.pending_status_requested_at
        and published_at >= subscription.pending_status_requested_at
    ):
        return False
    return True


def _has_started_pending_copied_bets(subscription: CopyBettingSubscription) -> bool:
    return (
        CopiedBet.objects.filter(
            subscription=subscription,
            state_status=CopiedBet.StateStatus.PENDING,
            source_coupon__predictions__match__starts_at__lte=timezone.now(),
        )
        .distinct()
        .exists()
    )


def _apply_pending_copybetting_status_if_ready(
    subscription: CopyBettingSubscription,
) -> CopyBettingSubscription:
    if not subscription.pending_status:
        return subscription
    if _has_started_pending_copied_bets(subscription):
        return subscription

    target_status = subscription.pending_status
    _apply_copybetting_status_locked(subscription, target_status)
    return subscription


def settle_orphaned_copied_bets(limit: int = 1000) -> int:
    from game.models import PredictionCoupon

    pending_bets = CopiedBet.objects.filter(state_status=CopiedBet.StateStatus.PENDING)
    settled_coupon_ids = list(
        pending_bets.filter(
            source_coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        )
        .exclude(source_coupon__state_status=PredictionCoupon.StateStatus.PENDING)
        .values_list("source_coupon_id", flat=True)
        .distinct()
        .order_by("source_coupon_id")[:limit]
    )
    # Copies of a coupon that is no longer published (canceled, or unpublished
    # before that was forbidden) can never be settled by result: refund them.
    voided_coupon_ids = list(
        pending_bets.exclude(
            source_coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        )
        .values_list("source_coupon_id", flat=True)
        .distinct()
        .order_by("source_coupon_id")[:limit]
    )
    if not settled_coupon_ids and not voided_coupon_ids:
        return 0

    settled_count = 0
    coupons = (
        PredictionCoupon.objects.filter(pk__in=[*settled_coupon_ids, *voided_coupon_ids])
        .select_related("author")
        .order_by("id")
    )
    for coupon in coupons:
        try:
            if coupon.published_status == PredictionCoupon.PublishedStatus.PUBLISHED:
                _copy_missing_bets_for_settlement(coupon)
                settled_count += len(settle_copied_bets_for_coupon(coupon))
            else:
                settled_count += len(
                    settle_copied_bets_for_coupon(
                        coupon,
                        outcome=PredictionCoupon.StateStatus.REFUND,
                    )
                )
        except Exception:
            logger.exception("Failed to reconcile copied bets for coupon #%s.", coupon.pk)
    return settled_count


def settle_copied_bets_for_coupon(
    coupon,
    *,
    outcome: str | None = None,
    change=None,
) -> list[CopiedBet]:
    """Bring copies of a coupon in line with its result.

    By default only pending copies are settled by the coupon result; ``outcome``
    overrides it when the coupon is voided without a result, e.g. canceled
    before the match. With a recorded result ``change`` (resettlement) already
    settled copies move to the new result too, and their coins are corrected by
    the difference.
    """
    from game.models import PredictionCoupon

    outcome = outcome or coupon.state_status
    copied_bets = CopiedBet.objects.filter(source_coupon=coupon)
    if change is None:
        if outcome == PredictionCoupon.StateStatus.PENDING:
            return []
        copied_bets = copied_bets.filter(state_status=CopiedBet.StateStatus.PENDING)
    change_subjects = _result_change_subjects(coupon)

    settled: list[CopiedBet] = []
    for copied_bet_id, reader_id in copied_bets.order_by("id").values_list("pk", "user_id"):
        try:
            with transaction.atomic():
                User.objects.select_for_update(no_key=True).get(pk=reader_id)
                locked_bet = (
                    CopiedBet.objects.select_for_update(of=("self",))
                    .select_related("user")
                    .get(pk=copied_bet_id)
                )
                if change is None and locked_bet.state_status != CopiedBet.StateStatus.PENDING:
                    continue

                previous = (locked_bet.state_status, locked_bet.possible_payout)
                previous_profit = locked_bet.profit
                credit_kind = CoinTransaction.Kind.COPYBET_PAYOUT
                if outcome == PredictionCoupon.StateStatus.WIN:
                    locked_bet.possible_payout = _copy_possible_payout(coupon, locked_bet.stake)
                    target = _coin_amount_from_model(
                        locked_bet.possible_payout,
                        field_name="Выплата по копиставке",
                    )
                    locked_bet.state_status = CopiedBet.StateStatus.WIN
                    locked_bet.profit = _coin_decimal_total(
                        locked_bet.possible_payout - locked_bet.stake
                    )
                elif outcome == PredictionCoupon.StateStatus.REFUND:
                    credit_kind = CoinTransaction.Kind.COPYBET_REFUND
                    target = _coin_amount_from_model(
                        locked_bet.stake,
                        field_name="Возврат копиставки",
                    )
                    locked_bet.state_status = CopiedBet.StateStatus.REFUND
                    locked_bet.profit = Decimal("0")
                elif outcome == PredictionCoupon.StateStatus.LOSE:
                    target = 0
                    locked_bet.state_status = CopiedBet.StateStatus.LOSE
                    locked_bet.profit = -_coin_decimal_total(locked_bet.stake)
                else:
                    # The coupon result was withdrawn: the copy waits for a new one.
                    target = 0
                    locked_bet.state_status = CopiedBet.StateStatus.PENDING
                    locked_bet.profit = Decimal("0")
                if (locked_bet.state_status, locked_bet.possible_payout) == previous:
                    continue

                locked_bet.settled_at = (
                    None
                    if locked_bet.state_status == CopiedBet.StateStatus.PENDING
                    else locked_bet.settled_at or timezone.now()
                )
                locked_bet.save(
                    update_fields=[
                        "state_status",
                        "possible_payout",
                        "profit",
                        "settled_at",
                    ]
                )
                subscription = CopyBettingSubscription.objects.select_for_update().get(
                    pk=locked_bet.subscription_id
                )
                _, _, uncollected = _settle_coins_to_target(
                    locked_bet.user,
                    target,
                    credit_kind=credit_kind,
                    reversal_kind=CoinTransaction.Kind.COPYBET_PAYOUT_REVERSAL,
                    settlement_kinds=COPYBET_SETTLEMENT_KINDS,
                    subject=locked_bet,
                    change=change,
                    change_subjects=change_subjects,
                    note=f"Расчет копиставки #{locked_bet.pk}",
                    reversal_note=f"Сторно по перерасчёту копиставки #{locked_bet.pk}",
                )
                if uncollected:
                    type(change).objects.filter(pk=change.pk).update(
                        uncollected_coins=F("uncollected_coins") + uncollected,
                    )

                subscription.total_profit = _coin_decimal_total(
                    subscription.total_profit + locked_bet.profit - previous_profit
                )
                current_loss = subscription.current_loss
                if previous_profit < 0:
                    # Undo the earlier loss. How much an earlier win reduced the
                    # drawdown is unknown (it never goes below zero): it stays.
                    current_loss = max(Decimal("0"), current_loss - abs(previous_profit))
                if locked_bet.profit < 0:
                    current_loss += abs(locked_bet.profit)
                elif locked_bet.profit > 0:
                    current_loss = max(Decimal("0"), current_loss - locked_bet.profit)
                subscription.current_loss = _coin_decimal_total(current_loss)
                update_fields = ["total_profit", "current_loss", "updated_at"]
                if (
                    subscription.stop_loss_amount > 0
                    and subscription.current_loss >= subscription.stop_loss_amount
                ):
                    subscription.status = CopyBettingSubscription.Status.STOPPED
                    subscription.pending_status = ""
                    subscription.pending_status_requested_at = None
                    subscription.stopped_at = timezone.now()
                    update_fields.extend(
                        ["status", "pending_status", "pending_status_requested_at", "stopped_at"]
                    )
                subscription.save(update_fields=update_fields)
                _apply_pending_copybetting_status_if_ready(subscription)
                settled.append(locked_bet)
        except Exception:
            logger.exception("Failed to settle copied bet #%s for coupon #%s.", copied_bet_id, coupon.pk)
    return settled


def _coin_wallet_for_update(user) -> CoinWallet:
    # Serialize wallet/copy operations without blocking foreign-key references.
    locked_user = User.objects.select_for_update(no_key=True).get(pk=user.pk)
    wallet, _ = CoinWallet.objects.get_or_create(user=locked_user)
    return CoinWallet.objects.select_for_update().get(pk=wallet.pk)


def _ensure_initial_coin_grant_locked(wallet: CoinWallet) -> None:
    if CoinTransaction.objects.filter(
        user=wallet.user,
        kind=CoinTransaction.Kind.INITIAL_GRANT,
    ).exists():
        return

    coin_settings = CoinSettings.load()
    if not coin_settings.is_enabled:
        return

    amount = int(coin_settings.initial_grant)
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
    amount = _coin_int(amount)
    new_balance = int(wallet.balance) + amount
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
        note=note[:255],
    )
    return wallet


def _has_coin_transaction(
    user,
    kind: str,
    related_model: str,
    related_id: int | None,
) -> bool:
    if related_id is None:
        return False
    return CoinTransaction.objects.filter(
        user=user,
        kind=kind,
        related_model=related_model,
        related_id=related_id,
    ).exists()


def _coin_related_subject(obj) -> tuple[str, int | None]:
    if obj is None:
        return "", None
    pk = getattr(obj, "pk", None)
    if pk is None:
        raise ValidationError("Связанный объект должен быть сохранен до операции с коинами.")
    return str(obj._meta.label_lower), int(pk)


def _require_coin_system_enabled() -> CoinSettings:
    coin_settings = CoinSettings.load()
    if not coin_settings.is_enabled:
        raise ValidationError("Система коинов временно отключена.")
    return coin_settings


def _validate_coin_kind(kind: str) -> None:
    if kind not in CoinTransaction.Kind.values:
        raise ValidationError("Неизвестный тип coin-транзакции.")


def _coin_int(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError("Количество коинов должно быть целым числом.")
    return value


def _coin_amount_from_model(value, *, field_name: str = "Коины") -> int:
    try:
        numeric = Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(f"{field_name} должны быть целым числом коинов.") from exc
    if not numeric.is_finite() or numeric != numeric.to_integral_value():
        raise ValidationError(f"{field_name} должны быть целым числом коинов.")
    return int(numeric)


def _rounded_coin_amount(value) -> int:
    try:
        numeric = Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError("Некорректная сумма коинов.") from exc
    if not numeric.is_finite():
        raise ValidationError("Некорректная сумма коинов.")
    return int(numeric.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _coin_decimal_input(value, field_name: str, *, allow_zero: bool = False) -> Decimal:
    amount = _coin_amount_from_model(value, field_name=field_name)
    if amount < 0 or (amount == 0 and not allow_zero):
        raise ValidationError(f"{field_name} должны быть больше нуля.")
    return Decimal(amount)


def _coin_decimal_total(value) -> Decimal:
    return Decimal(_rounded_coin_amount(value))


def _real_balance_for_update(user) -> CapperRealBalance:
    balance = CapperRealBalance.objects.select_for_update().filter(user=user).first()
    if balance is not None:
        return balance
    try:
        with transaction.atomic():
            return CapperRealBalance.objects.create(user=user, balance=Decimal("0.00"))
    except IntegrityError:
        return CapperRealBalance.objects.select_for_update().get(user=user)


def _validate_pending_withdrawal_transaction(transaction_obj: RealBalanceTransaction) -> None:
    if transaction_obj.kind != RealBalanceTransaction.Kind.WITHDRAWAL_REQUEST:
        raise ValidationError("Операция не является заявкой на вывод.")
    if transaction_obj.status != RealBalanceTransaction.Status.PENDING:
        raise ValidationError("Заявка уже обработана.")
    if transaction_obj.amount >= 0:
        raise ValidationError("Некорректная сумма заявки на вывод.")


def _apply_real_locked(
    balance: CapperRealBalance,
    amount: Decimal,
    kind: str,
    *,
    status: str = RealBalanceTransaction.Status.COMPLETED,
    related_model: str = "",
    related_id: int | None = None,
    note: str = "",
    payout_details: str = "",
) -> CapperRealBalance:
    amount = _money(amount)
    balance.balance = _money(balance.balance + amount)
    balance.save(update_fields=["balance", "updated_at"])
    RealBalanceTransaction.objects.create(
        user=balance.user,
        kind=kind,
        status=status,
        amount=amount,
        balance_after=balance.balance,
        related_model=related_model,
        related_id=related_id,
        note=note[:255],
        payout_details=payout_details[:255],
    )
    return balance


def _has_real_transaction(user, kind: str, related_model: str, related_id: int | None) -> bool:
    if related_id is None:
        return False
    return RealBalanceTransaction.objects.filter(
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


def _copy_stake(subscription: CopyBettingSubscription) -> Decimal:
    raw_stake = subscription.bank_amount * subscription.stake_percent / Decimal("100")
    stake = Decimal(_rounded_coin_amount(raw_stake))
    if subscription.max_single_stake > 0:
        stake = min(stake, subscription.max_single_stake)
    return Decimal(_rounded_coin_amount(stake))


def validate_copybetting_stake(*, bank_amount, stake_percent, max_single_stake):
    from game.services.coupon_validation import PREDICTION_STAKE_MIN_COINS

    stake = _copy_stake(SimpleNamespace(bank_amount=bank_amount, stake_percent=stake_percent, max_single_stake=max_single_stake))
    if stake < PREDICTION_STAKE_MIN_COINS:
        raise ValidationError(f"Минимальная сумма копируемой ставки — {int(PREDICTION_STAKE_MIN_COINS)} коинов. Увеличьте банк, процент или максимум на одну ставку.")
    return stake


def _copybetting_allows_coupon(subscription: CopyBettingSubscription, coupon, *, positions=None) -> bool:
    if coupon.audience == "paid":
        from cabinet.paid_predictions import user_has_paid_prediction_subscription
        if not user_has_paid_prediction_subscription(subscription.user, coupon.author_id):
            return False
    is_tournament_coupon = _coupon_is_tournament(coupon)
    if is_tournament_coupon and not subscription.copy_tournament_coupons:
        return False
    if not is_tournament_coupon and not subscription.copy_regular_coupons:
        return False

    coupon_coefficient = _coupon_total_coefficient(coupon)
    if coupon_coefficient < max(subscription.min_total_coefficient, Decimal("1.01")):
        return False

    allowed_sport_codes = set(subscription.allowed_sports.values_list("code", flat=True))
    if not allowed_sport_codes:
        return True

    coupon_sport_codes = {
        prediction.match.sport_code
        for prediction in (positions if positions is not None else coupon.predictions.select_related("match__sport"))
        if prediction.match_id
    }
    if not coupon_sport_codes:
        return False
    return coupon_sport_codes.issubset(allowed_sport_codes)


def _coupon_is_tournament(coupon) -> bool:
    return hasattr(coupon, "tournament_link")


def _coupon_total_coefficient(coupon) -> Decimal:
    if coupon.total_stake > 0 and coupon.possible_payout > 0:
        return _money(coupon.possible_payout / coupon.total_stake)
    total = Decimal("1.00")
    has_predictions = False
    for prediction in coupon.predictions.all():
        total *= prediction.coefficient
        has_predictions = True
    return _money(total if has_predictions else Decimal("0.00"))


def _copy_possible_payout(coupon, stake: Decimal) -> Decimal:
    if coupon.total_stake <= 0:
        return Decimal("0")
    coefficient = coupon.possible_payout / coupon.total_stake
    return Decimal(_rounded_coin_amount(stake * coefficient))


def _charge_copied_bet_stake(copied_bet: CopiedBet) -> CoinWallet:
    amount = _coin_amount_from_model(copied_bet.stake, field_name="Копиставка")
    return charge_coins(
        copied_bet.user,
        amount,
        CoinTransaction.Kind.COPYBET_STAKE,
        related_obj=copied_bet,
        note=f"Копирование прогноза #{copied_bet.source_coupon_id}",
    )


def _validate_analyst(user) -> None:
    if getattr(user, "role", None) != User.Role.ANALYST:
        raise PermissionDenied("Реальный баланс доступен только капперам.")


def _validate_real_balance_user(user) -> None:
    if not user or not getattr(user, "pk", None):
        raise ValidationError("Пользователь не найден.")
    if not getattr(user, "is_active", False):
        raise ValidationError("Пользователь не активен.")


MAX_COPYBETTING_CAPPERS = 30


def validate_copybetting_access(user_id, analyst_id, *, activating=False):
    if CopyBettingBlock.objects.filter(user_id=user_id, analyst_id=analyst_id, revoked_at__isnull=True).exists():
        raise ValidationError("Автор запретил вам копировать его прогнозы.")
    if activating:
        existing = CopyBettingSubscription.objects.filter(user_id=user_id, analyst_id=analyst_id, status__in=["active", "paused"]).exists()
        count = CopyBettingSubscription.objects.filter(user_id=user_id, status__in=["active", "paused"]).count()
        if not existing and count >= MAX_COPYBETTING_CAPPERS:
            raise ValidationError(f"Можно копировать не более {MAX_COPYBETTING_CAPPERS} капперов одновременно. Остановите одну из стратегий.")


def copybetting_day_start():
    from datetime import datetime, time
    site_timezone = timezone.get_default_timezone()
    return timezone.make_aware(datetime.combine(timezone.localdate(timezone=site_timezone), time.min), site_timezone)


def copybetting_within_global_limits(user_id, stake):
    limits = CopyBettingLimits.objects.filter(user_id=user_id).first()
    if not limits or not (limits.daily_budget or limits.daily_stop_loss):
        return True
    start = copybetting_day_start()
    if limits.daily_budget:
        spent = CopiedBet.objects.filter(user_id=user_id, created_at__gte=start).aggregate(total=Sum("stake"))["total"] or 0
        if spent + stake > limits.daily_budget:
            return False
    if limits.daily_stop_loss:
        profit = CopiedBet.objects.filter(user_id=user_id, settled_at__gte=start).aggregate(total=Sum("profit"))["total"] or 0
        if -profit >= limits.daily_stop_loss:
            return False
    return True


def block_copybetting_user(*, analyst, user, reason=""):
    if not analyst.is_analyst or analyst.pk == user.pk or user.is_analyst:
        raise PermissionDenied("Запрет доступен только автору для копирующего пользователя.")
    with transaction.atomic():
        User.objects.select_for_update(no_key=True).get(pk=user.pk)
        block, created = CopyBettingBlock.objects.get_or_create(analyst=analyst, user=user, revoked_at__isnull=True, defaults={"reason": str(reason)[:300]})
        if created:
            subscription = CopyBettingSubscription.objects.select_for_update().filter(analyst=analyst, user=user).first()
            if subscription:
                subscription.status = CopyBettingSubscription.Status.STOPPED
                subscription.pending_status = ""
                subscription.pending_status_requested_at = None
                subscription.stopped_at = timezone.now()
                subscription._transition_actor = analyst
                subscription._transition_reason = "Запрет автора"
                subscription.save(update_fields=["status", "pending_status", "pending_status_requested_at", "stopped_at", "updated_at"])
            notify_copybetting_block(block, revoked=False)
        return block


def unblock_copybetting_user(*, analyst, user):
    if not analyst.is_analyst or analyst.pk == user.pk:
        raise PermissionDenied
    with transaction.atomic():
        User.objects.select_for_update(no_key=True).get(pk=user.pk)
        block = CopyBettingBlock.objects.select_for_update().filter(analyst=analyst, user=user, revoked_at__isnull=True).first()
        if block:
            block.revoked_at = timezone.now()
            block.save(update_fields=["revoked_at"])
            notify_copybetting_block(block, revoked=True)
        return block


def notify_copybetting_block(block, *, revoked):
    from notifications.models import Notification
    from notifications.services import create_notification
    for recipient, actor in ((block.user, block.analyst), (block.analyst, block.user)):
        create_notification(recipient=recipient, actor=actor, kind=Notification.Kind.COPYBETTING,
                            title="Копирование снова разрешено" if revoked else "Копирование запрещено автором",
                            message="Можно повторно настроить копирование. Оно не включается автоматически." if revoked else "Новые копии не создаются. Уже принятые ставки будут рассчитаны.",
                            url=reverse("cabinet:profile") + "?tab=copybetting",
                            event_key=f"copybetting-block:{block.pk}:{'revoked' if revoked else 'created'}:{recipient.pk}")


def stop_copybetting_after_role_change(user):
    """Keep accepted bets and record why a newly promoted author stopped copying."""
    with transaction.atomic():
        User.objects.select_for_update(no_key=True).get(pk=user.pk)
        for subscription in CopyBettingSubscription.objects.select_for_update().filter(user=user).exclude(status="stopped"):
            subscription.status = CopyBettingSubscription.Status.STOPPED
            subscription.pending_status = ""
            subscription.pending_status_requested_at = None
            subscription.stopped_at = timezone.now()
            subscription._transition_actor = user
            subscription._transition_reason = "Пользователь стал каппером"
            subscription.save(update_fields=["status", "pending_status", "pending_status_requested_at", "stopped_at", "updated_at"])
