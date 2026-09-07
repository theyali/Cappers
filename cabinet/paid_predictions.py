from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from back.models import WebsiteSettings

from .models import (
    AnalystFollow,
    AnalystPaidPlan,
    AnalystPaidSubscription,
    AnalystProfile,
    User,
    paid_subscription_expires_at,
)
from wallets.models import RealBalanceTransaction
from wallets.services import credit_real_balance

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
    field = PLATFORM_FEE_FIELDS.get(int(duration_days or 0))
    if not field:
        return Decimal("0")
    return _decimal(getattr(WebsiteSettings.load(), field, 0))


def paid_subscription_capper_income(price, duration_days: int) -> Decimal:
    price = _decimal(price)
    fee_percent = platform_fee_percent_for_duration(duration_days)
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


def subscribe_to_paid_predictions(
    subscriber: User,
    analyst: User,
    plan: AnalystPaidPlan | int | None = None,
) -> AnalystPaidSubscription:
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

    now = timezone.now()
    capper_income = paid_subscription_capper_income(price, duration_days)
    with transaction.atomic():
        subscription, created = AnalystPaidSubscription.objects.select_for_update().get_or_create(
            subscriber=subscriber,
            analyst=analyst,
            defaults={
                "plan": selected_plan,
                "price": price,
                "duration_days": duration_days,
                "starts_at": now,
                "expires_at": paid_subscription_expires_at(
                    now,
                    duration_days=duration_days,
                ),
            },
        )
        if created:
            AnalystFollow.objects.get_or_create(follower=subscriber, analyst=analyst)
            if capper_income > 0:
                credit_real_balance(
                    analyst,
                    capper_income,
                    RealBalanceTransaction.Kind.SUBSCRIPTION_INCOME,
                    note=f"Подписка @{subscriber.username}: {plan_title}",
                )
            credit_referral_income(
                subscriber,
                price,
                REFERRAL_ACTION_SUBSCRIPTION,
                note=f"Реферал @{subscriber.username}: покупка подписки «{plan_title}»",
            )
            return subscription
        base_time = subscription.expires_at if subscription.expires_at > now else now
        subscription.plan = selected_plan
        subscription.price = price
        subscription.duration_days = duration_days
        subscription.expires_at = paid_subscription_expires_at(
            base_time,
            duration_days=duration_days,
        )
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
                note=f"Продление подписки @{subscriber.username}: {plan_title}",
            )
        credit_referral_income(
            subscriber,
            price,
            REFERRAL_ACTION_SUBSCRIPTION,
            note=f"Реферал @{subscriber.username}: продление подписки «{plan_title}»",
        )
    return subscription
