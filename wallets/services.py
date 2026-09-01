from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db import models

from cabinet.models import User

from .models import (
    BalanceTransaction,
    CapperBalance,
    CapperRealBalance,
    CopiedBet,
    CopyBettingSubscription,
    RealBalanceTransaction,
)


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
    return ensure_virtual_balance(user)


def ensure_virtual_balance(user) -> CapperBalance:
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


def transfer_real_to_virtual(user, amount, *, note: str = "") -> tuple[CapperRealBalance, CapperBalance]:
    _validate_analyst(user)
    amount = _money(amount)
    if amount <= 0:
        raise ValidationError("Сумма перевода должна быть больше нуля.")

    with transaction.atomic():
        real_balance = _real_balance_for_update(user)
        if real_balance.balance < amount:
            raise InsufficientBalance(
                f"Недостаточно средств на реальном балансе. Доступно {real_balance.balance} ₽, нужно {amount} ₽."
            )
        _apply_real_locked(
            real_balance,
            -amount,
            RealBalanceTransaction.Kind.VIRTUAL_TOP_UP,
            note=note or "Пополнение виртуального баланса",
        )
        virtual_balance = _balance_for_update(user)
        _ensure_initial_bonus_locked(virtual_balance)
        _apply_locked(
            virtual_balance,
            amount,
            BalanceTransaction.Kind.REAL_TO_VIRTUAL,
            note=note or "Пополнение с реального баланса",
        )
        return real_balance, virtual_balance


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
        balance.pending_withdrawal = _money(balance.pending_withdrawal + amount)
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
    balance = None
    has_author_stake = _has_transaction(
        coupon.author,
        BalanceTransaction.Kind.PREDICTION_STAKE,
        related_model,
        related_id,
    )

    if has_author_stake and coupon.state_status == PredictionCoupon.StateStatus.WIN:
        kind = BalanceTransaction.Kind.PREDICTION_PAYOUT
        amount = _money(coupon.possible_payout)
        note = f"Выплата по прогнозу #{coupon.pk}"
    elif has_author_stake and coupon.state_status == PredictionCoupon.StateStatus.REFUND:
        kind = BalanceTransaction.Kind.PREDICTION_REFUND
        amount = _money(coupon.total_stake)
        note = f"Возврат по прогнозу #{coupon.pk}"
    else:
        kind = ""
        amount = Decimal("0.00")
        note = ""

    if amount > 0:
        with transaction.atomic():
            balance = _balance_for_update(coupon.author)
            _ensure_initial_bonus_locked(balance)
            if not _has_transaction(coupon.author, kind, related_model, related_id):
                balance = _apply_locked(
                    balance,
                    amount,
                    kind,
                    related_model=related_model,
                    related_id=related_id,
                    note=note,
                )
    settle_copied_bets_for_coupon(coupon)
    return balance


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

    bank_amount = _money(bank_amount)
    stop_loss_amount = _money(stop_loss_amount)
    max_single_stake = _money(max_single_stake)
    min_total_coefficient = _money(min_total_coefficient)
    stake_percent = _money(stake_percent)
    if bank_amount <= 0:
        raise ValidationError("Укажите банк для копирования.")
    if not Decimal("0.01") <= stake_percent <= Decimal("100.00"):
        raise ValidationError("Процент от банка должен быть от 0.01 до 100.")
    if stop_loss_amount < 0 or max_single_stake < 0:
        raise ValidationError("Стоп-лосс и максимум ставки не могут быть отрицательными.")
    if min_total_coefficient < 0:
        raise ValidationError("Минимальный коэффициент не может быть отрицательным.")
    if not copy_regular_coupons and not copy_tournament_coupons:
        raise ValidationError("Выберите хотя бы один тип прогнозов для копирования.")

    ensure_virtual_balance(user)
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
            },
        )
        was_stopped = subscription.status == CopyBettingSubscription.Status.STOPPED
        subscription.bank_amount = bank_amount
        subscription.stake_percent = stake_percent
        subscription.stop_loss_amount = stop_loss_amount
        subscription.max_single_stake = max_single_stake
        subscription.min_total_coefficient = min_total_coefficient
        subscription.copy_regular_coupons = copy_regular_coupons
        subscription.copy_tournament_coupons = copy_tournament_coupons
        subscription.status = CopyBettingSubscription.Status.ACTIVE
        subscription.stopped_at = None
        if was_stopped:
            subscription.current_loss = Decimal("0.00")
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
                "stopped_at",
                "current_loss",
                "updated_at",
            ]
        )
        if allowed_sports is not None:
            subscription.allowed_sports.set(allowed_sports)
    return subscription


def pause_copybetting(subscription: CopyBettingSubscription) -> CopyBettingSubscription:
    if subscription.status != CopyBettingSubscription.Status.ACTIVE:
        return subscription
    subscription.status = CopyBettingSubscription.Status.PAUSED
    subscription.save(update_fields=["status", "updated_at"])
    return subscription


def resume_copybetting(subscription: CopyBettingSubscription) -> CopyBettingSubscription:
    if subscription.status == CopyBettingSubscription.Status.ACTIVE:
        return subscription
    subscription.status = CopyBettingSubscription.Status.ACTIVE
    subscription.stopped_at = None
    subscription.save(update_fields=["status", "stopped_at", "updated_at"])
    return subscription


def stop_copybetting(subscription: CopyBettingSubscription) -> CopyBettingSubscription:
    if subscription.status == CopyBettingSubscription.Status.STOPPED:
        return subscription
    subscription.status = CopyBettingSubscription.Status.STOPPED
    from django.utils import timezone

    subscription.stopped_at = timezone.now()
    subscription.save(update_fields=["status", "stopped_at", "updated_at"])
    return subscription


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
        )
        .exclude(user=coupon.author)
        .select_related("user", "analyst")
        .order_by("id")
    )

    for subscription in subscriptions:
        stake = _copy_stake(subscription)
        if stake <= 0:
            continue
        if not _copybetting_allows_coupon(subscription, coupon):
            continue
        if subscription.stop_loss_amount > 0 and subscription.current_loss >= subscription.stop_loss_amount:
            stop_copybetting(subscription)
            continue

        copied_bet, created = CopiedBet.objects.get_or_create(
            user=subscription.user,
            source_coupon=coupon,
            defaults={
                "subscription": subscription,
                "analyst": coupon.author,
                "stake": stake,
                "possible_payout": _copy_possible_payout(coupon, stake),
            },
        )
        if not created:
            continue

        try:
            _charge_copied_bet_stake(copied_bet)
        except InsufficientBalance:
            copied_bet.delete()
            continue

        CopyBettingSubscription.objects.filter(pk=subscription.pk).update(
            total_staked=models.F("total_staked") + stake
        )
        subscription.total_staked = _money(subscription.total_staked + stake)
        created_bets.append(copied_bet)

    return created_bets


def settle_copied_bets_for_coupon(coupon) -> list[CopiedBet]:
    from django.utils import timezone
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
        with transaction.atomic():
            locked_bet = CopiedBet.objects.select_for_update().select_related("subscription", "user").get(pk=copied_bet.pk)
            if locked_bet.state_status != CopiedBet.StateStatus.PENDING:
                continue

            subscription = CopyBettingSubscription.objects.select_for_update().get(pk=locked_bet.subscription_id)
            if coupon.state_status == PredictionCoupon.StateStatus.WIN:
                kind = BalanceTransaction.Kind.COPYBET_PAYOUT
                amount = locked_bet.possible_payout
                locked_bet.state_status = CopiedBet.StateStatus.WIN
                locked_bet.profit = _money(locked_bet.possible_payout - locked_bet.stake)
            elif coupon.state_status == PredictionCoupon.StateStatus.REFUND:
                kind = BalanceTransaction.Kind.COPYBET_REFUND
                amount = locked_bet.stake
                locked_bet.state_status = CopiedBet.StateStatus.REFUND
                locked_bet.profit = Decimal("0.00")
            else:
                kind = ""
                amount = Decimal("0.00")
                locked_bet.state_status = CopiedBet.StateStatus.LOSE
                locked_bet.profit = -locked_bet.stake

            locked_bet.settled_at = timezone.now()
            locked_bet.save(update_fields=["state_status", "profit", "settled_at"])

            if amount > 0:
                balance = _balance_for_update(locked_bet.user)
                _ensure_initial_bonus_locked(balance)
                related_model, related_id = _related_subject(locked_bet)
                if not _has_transaction(locked_bet.user, kind, related_model, related_id):
                    _apply_locked(
                        balance,
                        amount,
                        kind,
                        related_model=related_model,
                        related_id=related_id,
                        note=f"Расчет копиставки #{locked_bet.pk}",
                    )

            subscription.total_profit = _money(subscription.total_profit + locked_bet.profit)
            if locked_bet.profit < 0:
                subscription.current_loss = _money(subscription.current_loss + abs(locked_bet.profit))
            elif locked_bet.profit > 0:
                subscription.current_loss = max(
                    Decimal("0.00"),
                    _money(subscription.current_loss - locked_bet.profit),
                )
            update_fields = ["total_profit", "current_loss", "updated_at"]
            if subscription.stop_loss_amount > 0 and subscription.current_loss >= subscription.stop_loss_amount:
                subscription.status = CopyBettingSubscription.Status.STOPPED
                subscription.stopped_at = timezone.now()
                update_fields.extend(["status", "stopped_at"])
            subscription.save(update_fields=update_fields)
            settled.append(locked_bet)
    return settled


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
        note="Стартовый виртуальный баланс пользователя",
    )


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


def _has_transaction(user, kind: str, related_model: str, related_id: int | None) -> bool:
    if related_id is None:
        return False
    return BalanceTransaction.objects.filter(
        user=user,
        kind=kind,
        related_model=related_model,
        related_id=related_id,
    ).exists()


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
    stake = _money(subscription.bank_amount * subscription.stake_percent / Decimal("100"))
    if subscription.max_single_stake > 0:
        stake = min(stake, subscription.max_single_stake)
    return _money(stake)


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
        return Decimal("0.00")
    coefficient = _money(coupon.possible_payout / coupon.total_stake)
    return _money(stake * coefficient)


def _charge_copied_bet_stake(copied_bet: CopiedBet) -> CapperBalance:
    related_model, related_id = _related_subject(copied_bet)
    with transaction.atomic():
        balance = _balance_for_update(copied_bet.user)
        _ensure_initial_bonus_locked(balance)
        if _has_transaction(
            copied_bet.user,
            BalanceTransaction.Kind.COPYBET_STAKE,
            related_model,
            related_id,
        ):
            return balance
        if balance.balance < copied_bet.stake:
            raise InsufficientBalance(
                f"Недостаточно средств на виртуальном балансе. Доступно {balance.balance} ₽, нужно {copied_bet.stake} ₽."
            )
        return _apply_locked(
            balance,
            -copied_bet.stake,
            BalanceTransaction.Kind.COPYBET_STAKE,
            related_model=related_model,
            related_id=related_id,
            note=f"Копирование прогноза #{copied_bet.source_coupon_id}",
        )


def _validate_analyst(user) -> None:
    if getattr(user, "role", None) != User.Role.ANALYST:
        raise PermissionDenied("Реальный баланс доступен только капперам.")
