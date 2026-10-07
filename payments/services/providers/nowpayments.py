import hashlib
import hmac
import json
import logging
import math
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone

from payments.models import Payment

from .base import CheckoutSession, InvalidSignature, PaymentProvider, PaymentProviderError, ProviderEvent, Rejection
from .http import credentials_configured, parse_amount, request_json

logger = logging.getLogger("payments")

API_URLS = {
    False: "https://api.nowpayments.io/v1",
    True: "https://api-sandbox.nowpayments.io/v1",
}

PAYMENT_STATUSES = {
    "waiting": Payment.Status.PENDING,
    "confirming": Payment.Status.PROCESSING,
    "confirmed": Payment.Status.PROCESSING,
    "sending": Payment.Status.PROCESSING,
    "partially_paid": Payment.Status.PARTIALLY_PAID,
    "finished": Payment.Status.SUCCEEDED,
    "failed": Payment.Status.FAILED,
    "refunded": Payment.Status.REFUNDED,
    "expired": Payment.Status.EXPIRED,
}


@dataclass(frozen=True)
class NOWPaymentsProvider(PaymentProvider):
    code = Payment.Provider.NOWPAYMENTS.value
    title = "Криптовалюта"
    pay_label = "Оплатить криптой"

    api_key: str
    ipn_secret: str
    sandbox: bool
    timeout: int
    order_ttl_minutes: int
    fee_paid_by_user: bool
    min_amount_rub: int

    @classmethod
    def from_settings(cls) -> "NOWPaymentsProvider":
        return cls(
            api_key=settings.NOWPAYMENTS_API_KEY,
            ipn_secret=settings.NOWPAYMENTS_IPN_SECRET,
            sandbox=settings.NOWPAYMENTS_SANDBOX,
            timeout=settings.NOWPAYMENTS_API_TIMEOUT,
            order_ttl_minutes=settings.NOWPAYMENTS_ORDER_TTL_MINUTES,
            fee_paid_by_user=settings.NOWPAYMENTS_FEE_PAID_BY_USER,
            min_amount_rub=settings.NOWPAYMENTS_MIN_AMOUNT_RUB,
        )

    def is_enabled(self) -> bool:
        return credentials_configured(self.api_key, self.ipn_secret)

    def supports(self, amount_rub) -> bool:
        return amount_rub > 0 and amount_rub >= self.min_amount_rub

    def create_checkout(self, payment, *, success_url: str, fail_url: str, webhook_url: str) -> CheckoutSession:
        # The price goes in rubles: NOWPayments converts it to the coin the payer picks.
        invoice = self._call(
            "invoice",
            {
                "price_amount": float(payment.amount),
                "price_currency": payment.currency.lower(),
                "order_id": str(payment.public_id),
                "order_description": payment.product_snapshot.get("description") or payment.get_purpose_display(),
                "ipn_callback_url": webhook_url,
                "success_url": success_url,
                "cancel_url": fail_url,
                "is_fee_paid_by_user": self.fee_paid_by_user,
            },
        )
        if not invoice.get("invoice_url"):
            logger.error("NOWPayments did not create an invoice for payment %s: %s", payment.public_id, invoice.get("message"))
            raise PaymentProviderError("Не удалось создать оплату. Попробуйте позже.")
        return CheckoutSession(
            redirect_url=invoice["invoice_url"],
            external_invoice_id=str(invoice.get("id", "")),
            expires_at=timezone.now() + timedelta(minutes=self.order_ttl_minutes),
        )

    def verify_signature(self, request) -> None:
        # x-nowpayments-sig is HMAC-SHA512 of the JSON body with its keys sorted at every level.
        received = request.headers.get("x-nowpayments-sig", "").strip().lower().encode()
        try:
            data = json.loads(request.body)
        except ValueError as error:
            raise InvalidSignature("NOWPayments: тело уведомления не JSON.") from error
        if not isinstance(data, dict):
            raise InvalidSignature("NOWPayments: тело уведомления не объект.")
        expected = [
            hmac.new(self.ipn_secret.encode(), message, hashlib.sha512).hexdigest().encode()
            for message in _signed_forms(data)
        ]
        if not received or not any(hmac.compare_digest(received, digest) for digest in expected):
            raise InvalidSignature("NOWPayments: неверная подпись уведомления.")

    def parse_webhook(self, request, *, event_type: str) -> ProviderEvent:
        if event_type != "ipn":
            raise PaymentProviderError(f"NOWPayments: неизвестное уведомление «{event_type}».")
        payment_id = str(json.loads(request.body).get("payment_id") or "")
        if not payment_id.isdigit():
            raise PaymentProviderError("NOWPayments: нет payment_id.")
        # The notification only says that something changed; the status and the
        # amounts are taken from the API, so a leaked IPN secret cannot fake a payment.
        return self._payment_event("ipn", self._call(f"payment/{payment_id}"))

    def fetch_status(self, payment) -> ProviderEvent | None:
        payment_id = str(payment.provider_payload.get("payment_id") or payment.external_id or "")
        if not payment_id.isdigit():
            # No notification has arrived yet, so there is no payment to ask about.
            return None
        return self._payment_event("reconcile", self._call(f"payment/{payment_id}"))

    def webhook_response(self, *, rejection: Rejection | None = None):
        return JsonResponse({"status": "ok"})

    def _call(self, endpoint: str, body: dict | None = None) -> dict:
        return request_json(
            "NOWPayments",
            f"{API_URLS[self.sandbox]}/{endpoint}",
            headers={"x-api-key": self.api_key},
            body=body,
            timeout=self.timeout,
        )

    def _payment_event(self, event_type: str, data: dict) -> ProviderEvent:
        payment_status = str(data.get("payment_status") or "")
        status = PAYMENT_STATUSES.get(payment_status)
        payment_id = str(data.get("payment_id") or "")
        if status is None or not payment_id:
            raise PaymentProviderError(f"NOWPayments: неизвестный статус платежа «{payment_status}».")
        failed = status in (Payment.Status.FAILED, Payment.Status.EXPIRED)
        return ProviderEvent(
            event_type=event_type,
            payment_public_id=str(data.get("order_id") or ""),
            status=status,
            external_id=payment_id,
            amount=parse_amount(data.get("price_amount"), "NOWPayments"),
            currency=str(data.get("price_currency") or "").upper(),
            paid_amount=parse_amount(data.get("actually_paid"), "NOWPayments"),
            paid_currency=str(data.get("pay_currency") or "").upper(),
            is_test=self.sandbox,
            dedup_key=f"{event_type}:{payment_id}:{payment_status}",
            failure_reason=f"NOWPayments: {payment_status}" if failed else "",
            raw=data,
        )


def _signed_forms(data: dict) -> list[bytes]:
    """The sorted body as NOWPayments may have signed it.

    Their reference code is JavaScript (JSON.stringify): it keeps Cyrillic as
    is and writes 0.00001, while Python json.dumps, as in their Python example,
    escapes Cyrillic and writes 1e-05. Both forms need the IPN secret.
    """
    return [
        _js_json(data).encode(),
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode(),
    ]


def _js_json(value) -> str:
    if isinstance(value, dict):
        return "{" + ",".join(f"{_js_json(str(key))}:{_js_json(value[key])}" for key in sorted(value)) + "}"
    if isinstance(value, list):
        return "[" + ",".join(_js_json(item) for item in value) + "]"
    if isinstance(value, float):
        return _js_number(value)
    return json.dumps(value, ensure_ascii=False)


def _js_number(number: float) -> str:
    """A float the way JavaScript prints it."""
    if not math.isfinite(number):
        return "null"
    if number == int(number) and abs(number) < 1e21:
        return str(int(number))
    text = repr(number)
    if 1e-6 <= abs(number) < 1e21:
        return format(Decimal(text), "f")
    mantissa, exponent = text.split("e")
    return f"{mantissa}e{int(exponent):+d}"
