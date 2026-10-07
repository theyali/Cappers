import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from payments.models import Payment
from payments.services.fulfillment import fulfill_payment
from payments.services.processing import apply_provider_event
from payments.services.providers.base import PaymentProviderError
from payments.services.providers.factory import PaymentProviderFactory

logger = logging.getLogger("payments")

# A notification normally arrives within seconds; older open orders are checked.
RECONCILE_AFTER = timedelta(minutes=10)
RECONCILE_BATCH_SIZE = 200
# Unpaid orders stay open a little past their deadline so a payment in progress can finish.
EXPIRE_GRACE = timedelta(minutes=30)


@shared_task(autoretry_for=(Exception,), retry_backoff=True, retry_backoff_max=600, max_retries=5)
def fulfill_payment_task(payment_id: int) -> None:
    fulfill_payment(payment_id)


@shared_task
def reconcile_pending_payments() -> dict:
    """Make up for lost notifications: ask providers about open orders, deliver paid ones."""
    cutoff = timezone.now() - RECONCILE_AFTER
    providers = {}
    checked = delivered = 0

    open_payments = Payment.objects.filter(
        status__in=[Payment.Status.PENDING, Payment.Status.PROCESSING, Payment.Status.FAILED],
        created_at__lte=cutoff,
    ).order_by("created_at", "id")[:RECONCILE_BATCH_SIZE]
    for payment in open_payments:
        if payment.provider not in providers:
            try:
                providers[payment.provider] = PaymentProviderFactory.create(payment.provider)
            except PaymentProviderError:
                providers[payment.provider] = None
        provider = providers[payment.provider]
        if provider is None:
            continue
        try:
            event = provider.fetch_status(payment)
        except PaymentProviderError:
            continue
        checked += 1
        if event is not None:
            apply_provider_event(payment.provider, event)

    unfulfilled = Payment.objects.filter(
        status=Payment.Status.SUCCEEDED,
        fulfilled_at__isnull=True,
        paid_at__lte=cutoff,
    ).values_list("pk", flat=True)[:RECONCILE_BATCH_SIZE]
    for payment_id in unfulfilled:
        try:
            fulfill_payment(payment_id)
        except Exception:
            logger.exception("Payment %s could not be fulfilled", payment_id)
            continue
        delivered += 1
    return {"checked": checked, "delivered": delivered}


@shared_task
def expire_stale_payments() -> int:
    """Close unpaid orders; money that still arrives later wins (EXPIRED -> SUCCEEDED)."""
    now = timezone.now()
    expired = Payment.objects.filter(
        status__in=[Payment.Status.CREATED, Payment.Status.PENDING, Payment.Status.FAILED],
        expires_at__lt=now - EXPIRE_GRACE,
    ).update(status=Payment.Status.EXPIRED, updated_at=now)
    if expired:
        logger.info("Expired %s unpaid payments", expired)
    return expired
