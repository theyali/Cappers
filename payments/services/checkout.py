from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from cabinet.models import User, VipPlan
from cabinet.paid_predictions import paid_subscription_terms, platform_fee_percent_for_duration
from cabinet.vip import get_active_vip, validate_vip_purchase
from payments.models import Payment
from payments.services.providers.base import PaymentProviderError
from payments.services.providers.factory import PaymentProviderFactory
from wallets.models import CoinPackage, CoinSettings

# Unpaid orders a user may have open at once (different products; the same one is reused).
OPEN_PAYMENTS_LIMIT = 5
# An open order is reused only if the payer still has this long to pay it.
REUSE_MIN_TIME_LEFT = timedelta(minutes=10)


# Each *_order builds the Payment fields for a product, with the snapshot that
# fulfillment.py delivers by (PAYMENTS_INTEGRATION_PLAN.md, 4.1).


def coin_package_order(package_id) -> dict:
    package = CoinPackage.objects.filter(pk=_object_id(package_id), is_active=True, price_rub__gt=0).first()
    if package is None:
        raise ValidationError("Этот пакет коинов больше недоступен.")
    if not CoinSettings.load().is_enabled:
        raise ValidationError("Система коинов временно отключена.")
    return {
        "purpose": Payment.Purpose.COIN_PACKAGE,
        "amount_rub": package.price_rub,
        "coin_package": package,
        "product_snapshot": {
            "package_id": package.pk,
            "title": package.title,
            "coins": package.coins,
            "bonus_coins": package.bonus_coins,
            "price_rub": str(package.price_rub),
            "description": f"Пакет коинов «{package.title}»",
        },
    }


def paid_subscription_order(subscriber, analyst_id, plan_id) -> dict:
    analyst = User.objects.filter(pk=_object_id(analyst_id), role=User.Role.ANALYST, is_active=True).first()
    if analyst is None:
        raise ValidationError("Каппер не найден.")
    try:
        plan, price, duration_days, plan_title = paid_subscription_terms(subscriber, analyst, plan_id)
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc
    return {
        "purpose": Payment.Purpose.PAID_SUBSCRIPTION,
        "amount_rub": price,
        "paid_plan": plan,
        "product_snapshot": {
            "analyst_id": analyst.pk,
            "plan_id": plan.pk if plan else None,
            "plan_title": plan_title,
            "duration_days": duration_days,
            "price_rub": str(price),
            "platform_fee_percent": str(platform_fee_percent_for_duration(duration_days)),
            "description": f"Подписка на прогнозы @{analyst.username}: {plan_title}",
        },
    }


def vip_plan_order(user, plan_id, *, switch: bool) -> dict:
    plan = VipPlan.objects.filter(pk=_object_id(plan_id), price_rub__gt=0).first()
    if plan is None:
        raise ValidationError("VIP-тариф не найден.")
    validate_vip_purchase(user, plan, switch=switch)
    active_vip = get_active_vip(user)
    return {
        "purpose": Payment.Purpose.VIP_PLAN,
        "amount_rub": plan.price_rub,
        "vip_plan": plan,
        "product_snapshot": {
            "plan_id": plan.pk,
            "title": plan.title,
            "duration_days": plan.duration_days,
            "price_rub": str(plan.price_rub),
            "switch": bool(switch and active_vip and active_vip.plan_id != plan.pk),
            "description": f"VIP-тариф «{plan.title}» на {plan.duration_days} дн.",
        },
    }


def can_pay_with_providers(user) -> bool:
    """Whether this user is offered provider payments (see PAYMENTS_STAFF_ONLY)."""
    return not settings.PAYMENTS_STAFF_ONLY or bool(getattr(user, "is_staff", False))


def start_checkout(user, order: dict, provider_code: str, *, site_url: str) -> Payment:
    """Create the provider order for a product; the payer is sent to payment.checkout_url.

    ``site_url`` is the site root the payer comes back to after paying.

    Asking again for the same product reuses the open order instead of creating
    another one.
    """
    if not can_pay_with_providers(user):
        raise ValidationError("Этот способ оплаты сейчас недоступен.")
    try:
        provider = PaymentProviderFactory.create(provider_code)
    except PaymentProviderError as exc:
        raise ValidationError("Этот способ оплаты сейчас недоступен.") from exc
    amount_rub = Decimal(order["amount_rub"])
    if not provider.supports(amount_rub):
        raise ValidationError("Этим способом нельзя оплатить такую сумму.")

    now = timezone.now()
    open_payments = Payment.objects.filter(user=user, status=Payment.Status.PENDING, expires_at__gt=now)
    reusable = (
        open_payments.filter(
            provider=provider.code,
            purpose=order["purpose"],
            product_snapshot=order["product_snapshot"],
            expires_at__gt=now + REUSE_MIN_TIME_LEFT,
        )
        .exclude(checkout_url="")
        .order_by("-created_at")
        .first()
    )
    if reusable is not None:
        return reusable
    if open_payments.count() >= OPEN_PAYMENTS_LIMIT:
        raise ValidationError("Слишком много неоплаченных заказов. Оплатите их или подождите, пока они истекут.")

    payment = Payment.objects.create(
        user=user,
        provider=provider.code,
        amount=amount_rub,
        currency="RUB",
        **order,
    )
    return_url = site_url.rstrip("/") + reverse("payments:return", args=[payment.public_id])
    try:
        session = provider.create_checkout(payment, success_url=return_url, fail_url=return_url, webhook_url="")
    except PaymentProviderError as exc:
        payment.status = Payment.Status.FAILED
        payment.failure_reason = str(exc)[:255]
        payment.save(update_fields=["status", "failure_reason", "updated_at"])
        raise ValidationError(str(exc)) from exc

    payment.status = Payment.Status.PENDING
    payment.checkout_url = session.redirect_url
    payment.external_invoice_id = session.external_invoice_id
    payment.expires_at = session.expires_at
    payment.save(update_fields=["status", "checkout_url", "external_invoice_id", "expires_at", "updated_at"])
    return payment


def _object_id(value) -> int | None:
    value = str(value or "").strip()
    return int(value) if value.isdigit() else None
