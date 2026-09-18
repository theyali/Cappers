import logging
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from cabinet.models import User

from .models import (
    CapperRealBalance,
    CoinPackage,
    CoinSettings,
    CoinTransaction,
    CoinWallet,
    CopiedBet,
    CopyBettingSubscription,
    RealBalanceTransaction,
)


MONEY_QUANT = Decimal("0.01")
logger = logging.getLogger(__name__)


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
    if not package or not getattr(package, "pk", None):
        raise ValidationError("Пакет коинов не найден.")

    with transaction.atomic():
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
    _validate_analyst(user)
    with transaction.atomic():
        return _real_balance_for_update(user)


def credit_real_balance(
    user,
    amount,
    kind: str,
    *,
    related_obj: Any | None = None,
    note: str = "",
) -> CapperRealBalance:
    _validate_analyst(user)
    amount = _money(amount)
    if amount <= 0:
        raise ValidationError("Сумма зачисления должна быть больше нуля.")
    related_model, related_id = _related_subject(related_obj) if related_obj is not None else ("", None)

    with transaction.atomic():
        balance = _real_balance_for_update(user)
        if _has_real_transaction(user, kind, related_model, related_id):
            return balance
        return _apply_real_locked(
            balance,
            amount,
            kind,
            related_model=related_model,
            related_id=related_id,
            note=note,
        )


def request_real_withdrawal(user, amount, *, note: str = "") -> CapperRealBalance:
    _validate_analyst(user)
    amount = _money(amount)
    if amount <= 0:
        raise ValidationError("Сумма вывода должна быть больше нуля.")

    with transaction.atomic():
        balance = _real_balance_for_update(user)
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
        )
        return balance


def approve_real_withdrawal(withdrawal: RealBalanceTransaction) -> RealBalanceTransaction:
    with transaction.atomic():
        locked = RealBalanceTransaction.objects.select_for_update().get(pk=withdrawal.pk)
        _validate_pending_withdrawal_transaction(locked)
        balance = _real_balance_for_update(locked.user)
        balance.pending_withdrawal = max(
            Decimal("0.00"),
            _money(balance.pending_withdrawal - abs(locked.amount)),
        )
        balance.save(update_fields=["pending_withdrawal", "updated_at"])
        locked.status = RealBalanceTransaction.Status.COMPLETED
        locked.save(update_fields=["status"])
        return locked


def cancel_real_withdrawal(withdrawal: RealBalanceTransaction) -> RealBalanceTransaction:
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
        locked.save(update_fields=["status"])
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


def settle_prediction_coupon(coupon) -> CoinWallet | None:
    from game.models import PredictionCoupon

    if coupon.published_status != PredictionCoupon.PublishedStatus.PUBLISHED:
        return None
    if coupon.state_status == PredictionCoupon.StateStatus.PENDING:
        return None

    wallet = ensure_coin_wallet(coupon.author)
    stake_amount = _coin_amount_from_model(coupon.total_stake, field_name="Ставка")
    if stake_amount > 0:
        wallet = charge_coins(
            coupon.author,
            stake_amount,
            CoinTransaction.Kind.PREDICTION_STAKE,
            related_obj=coupon,
            note=f"Списание ставки по рассчитанному прогнозу #{coupon.pk}",
        )

    if coupon.state_status == PredictionCoupon.StateStatus.WIN:
        payout = _rounded_coin_amount(coupon.possible_payout)
        if payout > 0:
            wallet = credit_coins(
                coupon.author,
                payout,
                CoinTransaction.Kind.PREDICTION_PAYOUT,
                related_obj=coupon,
                note=f"Выплата по прогнозу #{coupon.pk}",
            )
    elif coupon.state_status == PredictionCoupon.StateStatus.REFUND and stake_amount > 0:
        wallet = credit_coins(
            coupon.author,
            stake_amount,
            CoinTransaction.Kind.PREDICTION_REFUND,
            related_obj=coupon,
            note=f"Возврат по прогнозу #{coupon.pk}",
        )

    _copy_missing_bets_for_settlement(coupon)
    settle_copied_bets_for_coupon(coupon)
    return wallet


def activate_copybetting(
    *,
    user,
    analyst,
    bank_amount,
    stake_percent,
    stop_loss_amount=0,
    max_single_stake=0,
    min_total_coefficient=0,
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
    if min_total_coefficient < 0:
        raise ValidationError("Минимальный коэффициент не может быть отрицательным.")
    if not copy_regular_coupons and not copy_tournament_coupons:
        raise ValidationError("Выберите хотя бы один тип прогнозов для копирования.")

    ensure_coin_wallet(user)
    active_since = timezone.now()
    with transaction.atomic():
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
        locked_subscription = CopyBettingSubscription.objects.select_for_update().get(pk=subscription.pk)
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
        locked_subscription = CopyBettingSubscription.objects.select_for_update().get(pk=subscription.pk)
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
        locked_subscription = (
            CopyBettingSubscription.objects.select_for_update()
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
        if stake <= 0:
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

    coupon_ids = list(
        CopiedBet.objects.filter(
            state_status=CopiedBet.StateStatus.PENDING,
            source_coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        )
        .exclude(source_coupon__state_status=PredictionCoupon.StateStatus.PENDING)
        .values_list("source_coupon_id", flat=True)
        .distinct()
        .order_by("source_coupon_id")[:limit]
    )
    if not coupon_ids:
        return 0

    settled_count = 0
    coupons = PredictionCoupon.objects.filter(pk__in=coupon_ids).select_related("author").order_by("id")
    for coupon in coupons:
        try:
            _copy_missing_bets_for_settlement(coupon)
            settled_count += len(settle_copied_bets_for_coupon(coupon))
        except Exception:
            logger.exception("Failed to reconcile copied bets for coupon #%s.", coupon.pk)
    return settled_count


def settle_copied_bets_for_coupon(coupon) -> list[CopiedBet]:
    from game.models import PredictionCoupon

    if coupon.state_status == PredictionCoupon.StateStatus.PENDING:
        return []

    settled: list[CopiedBet] = []
    copied_bets = (
        CopiedBet.objects.filter(
            source_coupon=coupon,
            state_status=CopiedBet.StateStatus.PENDING,
        )
        .select_related("subscription", "user")
        .order_by("id")
    )
    for copied_bet in copied_bets:
        try:
            with transaction.atomic():
                locked_bet = (
                    CopiedBet.objects.select_for_update()
                    .select_related("subscription", "user")
                    .get(pk=copied_bet.pk)
                )
                if locked_bet.state_status != CopiedBet.StateStatus.PENDING:
                    continue

                subscription = CopyBettingSubscription.objects.select_for_update().get(
                    pk=locked_bet.subscription_id
                )
                if coupon.state_status == PredictionCoupon.StateStatus.WIN:
                    locked_bet.possible_payout = _copy_possible_payout(coupon, locked_bet.stake)
                    kind = CoinTransaction.Kind.COPYBET_PAYOUT
                    amount = _coin_amount_from_model(
                        locked_bet.possible_payout,
                        field_name="Выплата по копиставке",
                    )
                    locked_bet.state_status = CopiedBet.StateStatus.WIN
                    locked_bet.profit = _coin_decimal_total(
                        locked_bet.possible_payout - locked_bet.stake
                    )
                elif coupon.state_status == PredictionCoupon.StateStatus.REFUND:
                    kind = CoinTransaction.Kind.COPYBET_REFUND
                    amount = _coin_amount_from_model(
                        locked_bet.stake,
                        field_name="Возврат копиставки",
                    )
                    locked_bet.state_status = CopiedBet.StateStatus.REFUND
                    locked_bet.profit = Decimal("0")
                else:
                    kind = ""
                    amount = 0
                    locked_bet.state_status = CopiedBet.StateStatus.LOSE
                    locked_bet.profit = -_coin_decimal_total(locked_bet.stake)

                locked_bet.settled_at = timezone.now()
                locked_bet.save(
                    update_fields=[
                        "state_status",
                        "possible_payout",
                        "profit",
                        "settled_at",
                    ]
                )

                if amount > 0:
                    credit_coins(
                        locked_bet.user,
                        amount,
                        kind,
                        related_obj=locked_bet,
                        note=f"Расчет копиставки #{locked_bet.pk}",
                    )

                subscription.total_profit = _coin_decimal_total(
                    subscription.total_profit + locked_bet.profit
                )
                if locked_bet.profit < 0:
                    subscription.current_loss = _coin_decimal_total(
                        subscription.current_loss + abs(locked_bet.profit)
                    )
                elif locked_bet.profit > 0:
                    subscription.current_loss = max(
                        Decimal("0"),
                        _coin_decimal_total(subscription.current_loss - locked_bet.profit),
                    )
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
            logger.exception("Failed to settle copied bet #%s for coupon #%s.", copied_bet.pk, coupon.pk)
    return settled


def _coin_wallet_for_update(user) -> CoinWallet:
    locked_user = User.objects.select_for_update().get(pk=user.pk)
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


def _copybetting_allows_coupon(subscription: CopyBettingSubscription, coupon) -> bool:
    is_tournament_coupon = _coupon_is_tournament(coupon)
    if is_tournament_coupon and not subscription.copy_tournament_coupons:
        return False
    if not is_tournament_coupon and not subscription.copy_regular_coupons:
        return False

    coupon_coefficient = _coupon_total_coefficient(coupon)
    if subscription.min_total_coefficient > 0 and coupon_coefficient < subscription.min_total_coefficient:
        return False

    allowed_sport_codes = set(subscription.allowed_sports.values_list("code", flat=True))
    if not allowed_sport_codes:
        return True

    coupon_sport_codes = {
        prediction.match.sport_code
        for prediction in coupon.predictions.select_related("match__sport")
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
