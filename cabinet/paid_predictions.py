from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from back.models import WebsiteSettings

from .models import (
    AnalystFollow,
    AnalystPaidPlan,
    AnalystPaidSubscription,
    AnalystPaidSubscriptionPayment,
    AnalystProfile,
    User,
    paid_subscription_expires_at,
)
from wallets.models import RealBalanceTransaction
from wallets.services import credit_real_balance, debit_real_balance, ensure_real_balance, format_money

from .referrals import REFERRAL_ACTION_SUBSCRIPTION, credit_referral_income


PLATFORM_FEE_FIELDS = {
    1: "platform_fee_1_day_percent",
    7: "platform_fee_7_days_percent",
    30: "platform_fee_30_days_percent",
    90: "platform_fee_90_days_percent",
    180: "platform_fee_180_days_percent",
}


def _decimal(value) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def platform_fee_percent_for_duration(duration_days: int) -> Decimal:
    # A plan of a non-standard length (e.g. 14 days from the admin) pays the fee of the
    # longest standard plan that fits into it, never zero.
    duration_days = max(int(duration_days or 0), min(PLATFORM_FEE_FIELDS))
    tier = max(days for days in PLATFORM_FEE_FIELDS if days <= duration_days)
    return _decimal(getattr(WebsiteSettings.load(), PLATFORM_FEE_FIELDS[tier], 0))


def paid_subscription_capper_income(price, duration_days: int, fee_percent=None) -> Decimal:
    """The capper's share; fee_percent fixed at checkout wins over the current settings."""
    price = _decimal(price)
    if fee_percent is None:
        fee_percent = platform_fee_percent_for_duration(duration_days)
    fee_percent = _decimal(fee_percent)
    fee_amount = (price * fee_percent / Decimal("100")).quantize(Decimal("0.01"))
    income = price - fee_amount
    return income if income > 0 else Decimal("0.00")


def profile_paid_predictions_enabled(user: User) -> bool:
    profile = getattr(user, "analyst_profile", None)
    if not profile or not profile.paid_predictions_enabled:
        return False
    if get_active_paid_plans(user).exists():
        return True
    if AnalystPaidPlan.objects.filter(analyst=user).exists():
        return False
    return bool(
        profile.paid_predictions_price
        and profile.paid_predictions_price > 0
    )


def get_active_paid_plans(analyst: User):
    return AnalystPaidPlan.objects.filter(
        analyst=analyst,
        is_active=True,
        price__gt=0,
        duration_days__gt=0,
    ).order_by("order", "duration_days", "id")


def build_paid_checkout_context(user, profile: AnalystProfile, paid_plans: list) -> dict:
    """Plan picker for buying a subscription with the real balance or through a provider."""
    from payments.utils import build_payment_options

    real_balance = ensure_real_balance(user)
    legacy_paid_price = profile.paid_predictions_price if not paid_plans else None
    prices = [plan.price for plan in paid_plans] or [legacy_paid_price or 0]
    payment_options = build_payment_options(max(prices), user)
    checked_plan_marked = False
    for paid_plan in paid_plans:
        paid_plan.can_afford = real_balance.balance >= paid_plan.price
        # A plan the balance does not cover can still be paid by card.
        paid_plan.is_selectable = paid_plan.can_afford or bool(payment_options)
        paid_plan.is_default_checked = False
        if paid_plan.can_afford and not checked_plan_marked:
            paid_plan.is_default_checked = True
            checked_plan_marked = True
    if paid_plans and not checked_plan_marked:
        paid_plans[0].is_default_checked = True
    legacy_can_afford = (
        real_balance.balance >= legacy_paid_price
        if legacy_paid_price and legacy_paid_price > 0
        else True
    )
    return {
        "paid_plans": paid_plans,
        "real_balance": real_balance,
        "real_balance_display": format_money(real_balance.balance),
        "legacy_paid_price": legacy_paid_price,
        "legacy_can_afford": legacy_can_afford,
        "legacy_is_selectable": legacy_can_afford or bool(payment_options),
        "paid_checkout_can_pay": any(plan.can_afford for plan in paid_plans) if paid_plans else legacy_can_afford,
        "payment_options": payment_options,
        "balance_pay_label": "Оплатить с баланса" if payment_options else "Оплатить подписку",
    }


def user_can_view_paid_predictions(user, analyst: User) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if user.pk == analyst.pk:
        return True
    return AnalystPaidSubscription.objects.filter(
        subscriber=user,
        analyst=analyst,
        expires_at__gt=timezone.now(),
    ).exists()


def active_paid_subscription_analyst_ids(user) -> set[int]:
    if not getattr(user, "is_authenticated", False):
        return set()
    return set(
        AnalystPaidSubscription.objects.filter(
            subscriber=user,
            expires_at__gt=timezone.now(),
        ).values_list("analyst_id", flat=True)
    )


def active_paid_subscriptions_by_analyst(user, analyst_ids: list[int] | set[int]):
    if not getattr(user, "is_authenticated", False) or not analyst_ids:
        return {}
    return {
        subscription.analyst_id: subscription
        for subscription in AnalystPaidSubscription.objects.filter(
            subscriber=user,
            analyst_id__in=analyst_ids,
            expires_at__gt=timezone.now(),
        )
    }


def _resolve_paid_plan(analyst: User, plan: AnalystPaidPlan | int | None):
    if plan is not None:
        try:
            plan_id = plan.pk if isinstance(plan, AnalystPaidPlan) else int(plan)
        except (TypeError, ValueError):
            raise ValueError("Выбранный тариф недоступен.")
        selected_plan = get_active_paid_plans(analyst).filter(pk=plan_id).first()
        if selected_plan is None:
            raise ValueError("Выбранный тариф недоступен.")
        return selected_plan

    return (
        get_active_paid_plans(analyst).filter(duration_days=30).first()
        or get_active_paid_plans(analyst).first()
    )


def paid_subscription_terms(
    subscriber: User,
    analyst: User,
    plan: AnalystPaidPlan | int | None = None,
) -> tuple[AnalystPaidPlan | None, Decimal, int, str]:
    """Check the subscription can be sold; return (plan, price, duration_days, plan_title)."""
    if subscriber.pk == analyst.pk:
        raise ValueError("Нельзя оформить платную подписку на самого себя.")
    if analyst.role != User.Role.ANALYST:
        raise ValueError("Платная подписка доступна только на аналитиков.")

    profile: AnalystProfile | None = AnalystProfile.objects.filter(user=analyst).first()
    if not profile or not profile.paid_predictions_enabled:
        raise ValueError("Этот эксперт не публикует платные прогнозы.")

    selected_plan = _resolve_paid_plan(analyst, plan)
    if selected_plan is not None:
        price = selected_plan.price
        duration_days = selected_plan.duration_days
        plan_title = selected_plan.title
    elif (
        not AnalystPaidPlan.objects.filter(analyst=analyst).exists()
        and profile.paid_predictions_price
        and profile.paid_predictions_price > 0
    ):
        price = profile.paid_predictions_price
        duration_days = 30
        plan_title = "30 дней"
    else:
        raise ValueError("У этого эксперта нет активных тарифов.")
    return selected_plan, price, duration_days, plan_title


def subscribe_to_paid_predictions(
    subscriber: User,
    analyst: User,
    plan: AnalystPaidPlan | int | None = None,
) -> AnalystPaidSubscription:
    """Buy a subscription with the real balance."""
    selected_plan, price, duration_days, plan_title = paid_subscription_terms(subscriber, analyst, plan)
    return grant_paid_subscription(
        subscriber,
        analyst,
        plan=selected_plan,
        price=price,
        duration_days=duration_days,
        plan_title=plan_title,
        capper_income=paid_subscription_capper_income(price, duration_days),
    )


def grant_paid_subscription(
    subscriber: User,
    analyst: User,
    *,
    plan: AnalystPaidPlan | None,
    price: Decimal,
    duration_days: int,
    plan_title: str,
    capper_income: Decimal,
    provider_payment=None,
) -> AnalystPaidSubscription:
    """Start or extend a subscription on the given terms.

    Without ``provider_payment`` the subscriber pays from the real balance here;
    with it the money is already taken by the payment provider.
    """
    now = timezone.now()
    with transaction.atomic():
        subscription, created = AnalystPaidSubscription.objects.select_for_update().get_or_create(
            subscriber=subscriber,
            analyst=analyst,
            defaults={
                "plan": plan,
                "price": price,
                "duration_days": duration_days,
                "starts_at": now,
                "expires_at": paid_subscription_expires_at(
                    now,
                    duration_days=duration_days,
                ),
            },
        )
        base_time = now if created else (subscription.expires_at if subscription.expires_at > now else now)
        expires_at = paid_subscription_expires_at(
            base_time,
            duration_days=duration_days,
        )
        payment = AnalystPaidSubscriptionPayment.objects.create(
            subscription=subscription,
            subscriber=subscriber,
            analyst=analyst,
            plan=plan,
            price=price,
            capper_income=capper_income,
            duration_days=duration_days,
            starts_at=base_time,
            expires_at=expires_at,
            payment=provider_payment,
        )
        if provider_payment is None:
            payment_note_prefix = "Покупка" if created else "Продление"
            debit_real_balance(
                subscriber,
                price,
                RealBalanceTransaction.Kind.PAID_PREDICTION_PURCHASE,
                related_obj=payment,
                note=f"{payment_note_prefix} подписки @{analyst.username}: {plan_title}",
            )
        if created:
            AnalystFollow.objects.get_or_create(follower=subscriber, analyst=analyst)
            if capper_income > 0:
                credit_real_balance(
                    analyst,
                    capper_income,
                    RealBalanceTransaction.Kind.SUBSCRIPTION_INCOME,
                    related_obj=payment,
                    note=f"Подписка @{subscriber.username}: {plan_title}",
                )
            credit_referral_income(
                subscriber,
                price - capper_income,
                REFERRAL_ACTION_SUBSCRIPTION,
                related_obj=payment,
                note=f"Реферал @{subscriber.username}: покупка подписки «{plan_title}»",
                seller=analyst,
            )
            return subscription
        subscription.plan = plan
        subscription.price = price
        subscription.duration_days = duration_days
        subscription.expires_at = expires_at
        if subscription.starts_at > now:
            subscription.starts_at = now
        subscription.save(
            update_fields=[
                "plan",
                "price",
                "duration_days",
                "starts_at",
                "expires_at",
                "updated_at",
            ]
        )
        AnalystFollow.objects.get_or_create(follower=subscriber, analyst=analyst)
        if capper_income > 0:
            credit_real_balance(
                analyst,
                capper_income,
                RealBalanceTransaction.Kind.SUBSCRIPTION_INCOME,
                related_obj=payment,
                note=f"Продление подписки @{subscriber.username}: {plan_title}",
            )
        credit_referral_income(
            subscriber,
            price - capper_income,
            REFERRAL_ACTION_SUBSCRIPTION,
            related_obj=payment,
            note=f"Реферал @{subscriber.username}: продление подписки «{plan_title}»",
            seller=analyst,
        )
    return subscription
