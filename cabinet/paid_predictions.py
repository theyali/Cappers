from decimal import Decimal, InvalidOperation
from datetime import timezone as datetime_timezone

from django.db import transaction
from django.db.models import OuterRef, Subquery, Sum
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format

from back.models import WebsiteSettings

from .models import (
    AnalystFollow,
    AnalystPaidPlan,
    AnalystPaidSubscription,
    AnalystPaidSubscriptionPayment,
    AnalystProfile,
    PaidPredictionPurchase,
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
    return profile_single_coupon_sales_enabled(user) or profile_paid_subscriptions_enabled(user)


def profile_single_coupon_sales_enabled(user) -> bool:
    profile = getattr(user, "analyst_profile", None)
    return bool(
        profile and profile.paid_predictions_enabled and profile.single_coupon_sales_enabled
        and profile.single_coupon_price and profile.single_coupon_price > 0
    )


def profile_paid_subscriptions_enabled(user) -> bool:
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


def build_paid_plan_choices(profile, paid_plans, *, selected_plan_id=None):
    """Public prices and checkout use the same period, daily price and discount."""
    legacy_paid_price = profile.paid_predictions_price if not paid_plans else None
    choices = [
        {"id": str(plan.pk), "label": plan.period_label, "days": plan.duration_days, "price": plan.price}
        for plan in paid_plans
    ] or [{"id": "", "label": "30 дней", "days": 30, "price": legacy_paid_price or Decimal("0")}]
    shortest = min(choices, key=lambda choice: choice["days"])
    base_daily = shortest["price"] / shortest["days"]
    best = min(choices, key=lambda choice: (choice["price"] / choice["days"], choice["days"]))
    default = next((choice for choice in choices if choice["id"] == str(selected_plan_id)), None)
    default = default or next((choice for choice in choices if choice["days"] == 30), choices[0])
    for choice in choices:
        price = choice["price"]
        daily = price / choice["days"]
        choice.update(
            short_label=f"{choice['days'] // 30} мес" if choice["days"] > 30 and choice["days"] % 30 == 0 else f"{choice['days']}д",
            price=str(price), price_label=format_money(price),
            daily_label=format_money(daily.quantize(Decimal("1"))),
            discount=max(0, int((1 - daily / base_daily) * 100)) if base_daily else 0,
            is_best_value=choice is best and daily < base_daily,
            is_default=choice is default,
        )
    return choices


def build_public_paid_tariffs_context(viewer, profile, paid_plans, *, next_url, subscription=None):
    from urllib.parse import urlencode
    from django.conf import settings
    from .vip import plural_ru

    choices = build_paid_plan_choices(profile, paid_plans)
    checkout_url = reverse("cabinet:paid_predictions_subscribe", args=[profile.user_id])
    is_self = getattr(viewer, "pk", None) == profile.user_id
    for choice in choices:
        choice["action_url"] = (
            reverse("cabinet:profile") + "?tab=settings#paid-predictions-settings"
            if is_self else checkout_url + "?" + urlencode({"plan_id": choice["id"], "next": next_url})
        )
        choice["action_label"] = "Настроить" if is_self else "Продлить" if subscription else "Выбрать"
        choice["rail_label"] = "Настроить тарифы" if is_self else "Продлить подписку" if subscription else "Оформить подписку"
        choice["mobile_label"] = "Настроить тарифы" if is_self else f"{'Продлить' if subscription else 'Оформить'} за {choice['price_label']} ₽"
    now = timezone.now()
    subscribers = AnalystPaidSubscription.objects.filter(
        analyst_id=profile.user_id, starts_at__lte=now, expires_at__gt=now, subscriber__is_active=True,
    ).count()
    single_enabled = getattr(settings, "SINGLE_COUPON_SALES_ENABLED", False) and profile_single_coupon_sales_enabled(profile.user)
    return {
        "plans": choices,
        "default_plan": next(choice for choice in choices if choice["is_default"]),
        "subscribers_label": f"{subscribers} {plural_ru(subscribers, 'подписчик', 'подписчика', 'подписчиков')}",
        "single_price_label": format_money(profile.single_coupon_price) if single_enabled else "",
        "paid_predictions_url": reverse("front:predictions") + "?" + urlencode({"prediction_type": "paid", "capper": profile.user_id}),
    }


def build_paid_checkout_context(user, profile: AnalystProfile, paid_plans: list, *, in_telegram_app: bool = False, selected_plan_id=None) -> dict:
    """Plan picker for buying a subscription with the real balance or through a provider."""
    from payments.utils import build_payment_options

    can_use_balance = user.role == User.Role.ANALYST
    real_balance = ensure_real_balance(user) if can_use_balance else None
    balance = real_balance.balance if real_balance else Decimal("0")
    choices = build_paid_plan_choices(profile, paid_plans, selected_plan_id=selected_plan_id)
    subscription = active_paid_subscriptions(user).filter(analyst_id=profile.user_id).first()
    starts_at = max(timezone.now(), subscription.expires_at) if subscription else timezone.now()
    default = next(choice for choice in choices if choice["is_default"])
    options_by_code = {}
    for choice in choices:
        price = Decimal(choice["price"])
        methods = build_payment_options(price, user, in_telegram_app=in_telegram_app)
        options_by_code.update({method["code"]: method for method in methods})
        choice.update(
            can_afford=can_use_balance and balance >= price,
            providers=[method["code"] for method in methods],
            expires_label=date_format(timezone.localtime(paid_subscription_expires_at(starts_at, duration_days=choice["days"])), "j E Y, H:i"),
            is_default=choice is default,
        )
    return {
        "subscription_choices": choices,
        "subscription_default": default,
        "can_use_subscription_balance": can_use_balance,
        "real_balance_display": format_money(balance),
        "payment_options": list(options_by_code.values()),
    }


def user_has_paid_prediction_subscription(user, analyst_id: int) -> bool:
    """Copying requires the author's subscription, never a one-off coupon unlock."""
    return active_paid_subscriptions(user).filter(analyst_id=analyst_id, starts_at__lte=timezone.now()).exists()


def user_can_view_paid_predictions(user, analyst: User) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    return user.pk == analyst.pk or user_has_paid_prediction_subscription(user, analyst.pk)


def paid_coupon_purchases(user):
    if not getattr(user, "is_authenticated", False):
        return PaidPredictionPurchase.objects.none()
    return PaidPredictionPurchase.objects.filter(
        buyer=user, status=PaidPredictionPurchase.Status.PAID,
        paid_at__isnull=False, refunded_at__isnull=True,
    )


def paid_coupon_purchase_ids(user, coupon_ids):
    """One query for a whole page; purchases never grant access to an author."""
    if not getattr(user, "is_authenticated", False) or not coupon_ids:
        return set()
    return set(paid_coupon_purchases(user).filter(coupon_id__in=coupon_ids)
               .values_list("coupon_id", flat=True))


def user_can_view_paid_coupon(user, coupon) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    return (
        user_can_view_paid_predictions(user, coupon.author)
        or bool(paid_coupon_purchase_ids(user, [coupon.pk]))
    )


def accessible_paid_coupon_ids(user, coupons):
    """Resolve all paid rights in two queries, independent of page length."""
    coupons = list(coupons)
    if not getattr(user, "is_authenticated", False):
        return set()
    author_ids = active_paid_subscription_analyst_ids(user)
    accessible_ids = {
        coupon.pk for coupon in coupons
        if coupon.author_id == user.pk or coupon.author_id in author_ids
    }
    return accessible_ids | paid_coupon_purchase_ids(user, [coupon.pk for coupon in coupons])


def active_paid_subscription_analyst_ids(user) -> set[int]:
    if not getattr(user, "is_authenticated", False):
        return set()
    return set(
        active_paid_subscriptions(user).filter(starts_at__lte=timezone.now()).values_list("analyst_id", flat=True)
    )


def active_paid_subscriptions(user, *, with_payments=False):
    """Only the viewer's own active access, never the capper's audience."""
    if not getattr(user, "is_authenticated", False):
        return AnalystPaidSubscription.objects.none()
    subscriptions = AnalystPaidSubscription.objects.filter(subscriber=user, expires_at__gt=timezone.now())
    if with_payments:
        payments = AnalystPaidSubscriptionPayment.objects.filter(
            subscription_id=OuterRef("pk"), subscriber=user,
        ).order_by().values("subscription_id").annotate(total=Sum("price"))
        subscriptions = subscriptions.annotate(total_paid=Subquery(payments.values("total")[:1]))
    return subscriptions


def active_paid_subscriptions_by_analyst(user, analyst_ids: list[int] | set[int], *, with_payments=False):
    if not getattr(user, "is_authenticated", False) or not analyst_ids:
        return {}
    return {
        subscription.analyst_id: subscription
        for subscription in active_paid_subscriptions(user, with_payments=with_payments).filter(analyst_id__in=analyst_ids)
    }


def paid_subscription_display(subscription, *, at=None):
    """Saved payment facts and an absolute-time countdown; no current plan price."""
    now = at or timezone.now()
    seconds = (subscription.expires_at.astimezone(datetime_timezone.utc) - now.astimezone(datetime_timezone.utc)).total_seconds()
    if seconds <= 0:
        remaining = "Подписка завершена"
    elif seconds < 3600:
        remaining = "Осталось менее часа"
    else:
        days, hours = divmod(int(seconds // 3600), 24)
        remaining = f"Осталось: {days} дн. {hours} ч."
    total_paid = getattr(subscription, "total_paid", None)
    return {
        "amount_caption": "Всего оплачено" if total_paid is not None else "Стоимость подписки",
        "amount_label": format_money(total_paid if total_paid is not None else subscription.price),
        "expires_label": date_format(timezone.localtime(subscription.expires_at), "j E Y, H:i"),
        "expires_iso": subscription.expires_at.isoformat(),
        "remaining_label": remaining,
    }


def build_paid_subscriptions_preview(user, *, limit=3):
    subscriptions = active_paid_subscriptions(user, with_payments=True).select_related(
        "analyst__analyst_profile",
    ).order_by("expires_at", "pk")[:limit]
    result = []
    for subscription in subscriptions:
        analyst = subscription.analyst
        profile = getattr(analyst, "analyst_profile", None)
        result.append({
            "username": analyst.username,
            "name": (profile.display_name if profile else "") or analyst.get_full_name() or analyst.username,
            "url": reverse("front:expert_profile", kwargs={"username": analyst.username}),
            "details": paid_subscription_display(subscription),
        })
    return result


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
        list(User.objects.select_for_update(no_key=True).filter(pk__in=[subscriber.pk, analyst.pk]).order_by("pk"))
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
