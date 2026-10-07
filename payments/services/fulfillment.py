import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from cabinet.models import AnalystPaidPlan, AnalystProfile, User, VipPlan
from cabinet.paid_predictions import grant_paid_subscription, paid_subscription_capper_income
from cabinet.vip import grant_paid_vip
from payments.models import Payment
from wallets.models import CoinPackage
from wallets.services import purchase_coin_package

logger = logging.getLogger("payments")


# Every product is delivered by Payment.product_snapshot, the terms at checkout,
# never by the current package, plan or price.


def fulfill_coin_package(payment: Payment) -> None:
    terms = payment.product_snapshot
    package = CoinPackage(
        pk=terms["package_id"],
        title=terms["title"],
        coins=int(terms["coins"]),
        bonus_coins=int(terms.get("bonus_coins") or 0),
        price_rub=Decimal(terms["price_rub"]),
    )
    purchase_coin_package(payment.user, package, payment=payment)


def fulfill_paid_subscription(payment: Payment) -> None:
    terms = payment.product_snapshot
    price = Decimal(terms["price_rub"])
    duration_days = int(terms["duration_days"])
    grant_paid_subscription(
        payment.user,
        User.objects.get(pk=terms["analyst_id"]),
        plan=AnalystPaidPlan.objects.filter(pk=terms.get("plan_id")).first(),
        price=price,
        duration_days=duration_days,
        plan_title=terms["plan_title"],
        capper_income=paid_subscription_capper_income(price, duration_days, terms["platform_fee_percent"]),
        provider_payment=payment,
    )


def fulfill_vip_plan(payment: Payment) -> None:
    terms = payment.product_snapshot
    grant_paid_vip(
        payment.user,
        VipPlan.objects.filter(pk=terms.get("plan_id")).first(),
        duration_days=int(terms["duration_days"]),
        switch=bool(terms.get("switch")),
        provider_payment=payment,
    )


FULFILLERS = {
    Payment.Purpose.COIN_PACKAGE: fulfill_coin_package,
    Payment.Purpose.PAID_SUBSCRIPTION: fulfill_paid_subscription,
    Payment.Purpose.VIP_PLAN: fulfill_vip_plan,
}


def fulfill_payment(payment_id: int) -> Payment:
    """Deliver what a succeeded payment bought, exactly once."""
    with transaction.atomic():
        payment = Payment.objects.select_for_update().select_related("user").get(pk=payment_id)
        if payment.status != Payment.Status.SUCCEEDED or payment.fulfilled_at:
            return payment
        FULFILLERS[payment.purpose](payment)
        payment.fulfilled_at = timezone.now()
        payment.save(update_fields=["fulfilled_at", "updated_at"])
    logger.info("Payment %s fulfilled: %s", payment.public_id, payment.purpose)
    return payment


def delivery_blocker(payment: Payment) -> str:
    """Why the product can no longer be delivered; asked before the money is taken."""
    if not payment.user.is_active:
        return "Аккаунт покупателя удалён."
    if payment.purpose == Payment.Purpose.PAID_SUBSCRIPTION:
        selling = AnalystProfile.objects.filter(
            user_id=payment.product_snapshot.get("analyst_id"),
            user__role=User.Role.ANALYST,
            user__is_active=True,
            paid_predictions_enabled=True,
        ).exists()
        if not selling:
            return "Каппер больше не продаёт платные прогнозы."
    if payment.purpose == Payment.Purpose.VIP_PLAN and not payment.user.is_analyst:
        return "VIP-тарифы доступны только капперам."
    return ""
