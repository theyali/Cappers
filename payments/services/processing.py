import logging
import sys
import uuid

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from payments.models import Payment, PaymentEvent
from payments.services.fulfillment import delivery_blocker
from payments.services.providers.base import ProviderEvent, Rejection

logger = logging.getLogger("payments")

S = Payment.Status
ALLOWED_TRANSITIONS = {
    S.CREATED: {S.PENDING, S.PROCESSING, S.PARTIALLY_PAID, S.SUCCEEDED, S.FAILED, S.CANCELED, S.EXPIRED},
    S.PENDING: {S.PROCESSING, S.PARTIALLY_PAID, S.SUCCEEDED, S.FAILED, S.CANCELED, S.EXPIRED},
    S.PROCESSING: {S.PARTIALLY_PAID, S.SUCCEEDED, S.FAILED, S.CANCELED, S.EXPIRED},
    S.PARTIALLY_PAID: {S.PROCESSING, S.SUCCEEDED, S.EXPIRED},
    # A declined card can be retried on the same order.
    S.FAILED: {S.PENDING, S.PROCESSING, S.SUCCEEDED, S.CANCELED, S.EXPIRED},
    # Money that arrived anyway always wins: it is delivered or refunded, never lost.
    S.CANCELED: {S.SUCCEEDED},
    S.EXPIRED: {S.SUCCEEDED},
    S.SUCCEEDED: {S.REFUNDED},
    S.REFUNDED: set(),
}
# The payer may still pay an order in these statuses.
PAYABLE_STATUSES = {S.PENDING, S.PROCESSING, S.FAILED}


def apply_provider_event(provider_code: str, event: ProviderEvent) -> Rejection | None:
    """Record a provider notification and move the payment by it; a repeat changes nothing.

    A "check" event changes nothing either: it asks whether the money may be
    taken, and the answer is the returned rejection (None to take it).
    """
    with transaction.atomic():
        payment = _locked_payment(provider_code, event.payment_public_id)
        log, _ = PaymentEvent.objects.get_or_create(
            provider=provider_code,
            dedup_key=event.dedup_key,
            defaults={
                "payment": payment,
                "event_type": event.event_type,
                "external_id": event.external_id,
                "payload": event.raw,
                "signature_valid": True,
            },
        )
        if log.processed_at and event.event_type != "check":
            return None

        rejection, error = _rejection(payment, event)
        if event.event_type == "check":
            if rejection:
                logger.info("Payment check %s refused: %s", event.dedup_key, error)
        elif error:
            # The money may already be taken: an admin has to look at it.
            logger.error("Payment event %s not applied: %s", event.dedup_key, error)
            rejection = None
        else:
            error = _move(payment, event)
        log.error = error
        log.processed_at = timezone.now()
        log.save(update_fields=["error", "processed_at"])
    return rejection


def _locked_payment(provider_code: str, public_id: str) -> Payment | None:
    try:
        public_id = uuid.UUID(public_id)
    except ValueError:
        return None
    return Payment.objects.select_for_update().filter(provider=provider_code, public_id=public_id).first()


def _rejection(payment: Payment | None, event: ProviderEvent) -> tuple[Rejection | None, str]:
    if payment is None:
        return Rejection.UNKNOWN_PAYMENT, "Платёж не найден."
    if event.account_id is not None and event.account_id != str(payment.user_id):
        return Rejection.WRONG_ACCOUNT, f"Плательщик {event.account_id} не совпадает с заказом."
    if (event.amount is not None and event.amount != payment.amount) or (
        event.currency and event.currency != payment.currency
    ):
        return (
            Rejection.WRONG_AMOUNT,
            f"Сумма {event.amount} {event.currency} не совпадает с заказом: {payment.amount} {payment.currency}.",
        )
    if event.is_test and not settings.PAYMENTS_ALLOW_TEST_PAYMENTS:
        return Rejection.NOT_PAYABLE, "Тестовый платёж, а тестовые оплаты выключены."
    if event.event_type == "check":
        if payment.status == S.EXPIRED or (payment.expires_at and payment.expires_at <= timezone.now()):
            return Rejection.EXPIRED, "Срок оплаты истёк."
        if payment.status not in PAYABLE_STATUSES:
            return Rejection.NOT_PAYABLE, f"Платёж в статусе «{payment.get_status_display()}» оплатить нельзя."
        blocker = delivery_blocker(payment)
        if blocker:
            return Rejection.NOT_PAYABLE, blocker
    return None, ""


def _move(payment: Payment, event: ProviderEvent) -> str:
    current, new = payment.status, event.status
    if new != current and new not in ALLOWED_TRANSITIONS[current]:
        logger.warning("Payment %s: %s -> %s is not allowed, event %s skipped", payment.public_id, current, new, event.dedup_key)
        return f"Статус «{payment.get_status_display()}» не меняется на «{S(new).label}»."

    fields = ["status", "provider_payload", "updated_at"]
    payment.status = new
    payment.provider_payload = event.raw
    if new == S.SUCCEEDED:
        payment.external_id = event.external_id
        payment.paid_amount = event.paid_amount if event.paid_amount is not None else event.amount
        payment.paid_currency = event.paid_currency or event.currency
        payment.is_test = event.is_test
        payment.failure_reason = ""
        if payment.paid_at is None:
            payment.paid_at = timezone.now()
        fields += ["external_id", "paid_amount", "paid_currency", "is_test", "failure_reason", "paid_at"]
        if current != S.SUCCEEDED:
            payment_id = payment.pk
            transaction.on_commit(lambda: _fulfill(payment_id))
    elif new == S.FAILED:
        payment.failure_reason = event.failure_reason
        fields.append("failure_reason")
    elif new == S.REFUNDED and payment.refunded_at is None:
        payment.refunded_at = timezone.now()
        fields.append("refunded_at")
    payment.save(update_fields=fields)
    logger.info("Payment %s: %s -> %s by %s", payment.public_id, current, new, event.dedup_key)
    return ""


def _fulfill(payment_id: int) -> None:
    # Delivery runs in its own task: a failure there is retried by Celery and the
    # reconciliation, not by the provider resending the notification.
    from payments.tasks import fulfill_payment_task

    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False) or "test" in sys.argv:
        fulfill_payment_task(payment_id)
    else:
        fulfill_payment_task.delay(payment_id)
