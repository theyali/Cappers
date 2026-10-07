import base64
import hashlib
import hmac
import json
import logging
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone

from payments.models import Payment

from .base import CheckoutSession, InvalidSignature, PaymentProvider, PaymentProviderError, ProviderEvent, Rejection

logger = logging.getLogger("payments")

# Credentials from .env.example contain it; a secret everyone can read must
# never be trusted to verify notifications.
PLACEHOLDER_MARK = "change-me"

# Answers to the Check notification; Pay, Fail and Refund expect 0.
REJECTION_CODES = {
    Rejection.UNKNOWN_PAYMENT: 10,
    Rejection.WRONG_ACCOUNT: 11,
    Rejection.WRONG_AMOUNT: 12,
    Rejection.NOT_PAYABLE: 13,
    Rejection.EXPIRED: 20,
}

NOTIFICATION_STATUSES = {
    "check": Payment.Status.PENDING,
    "pay": Payment.Status.SUCCEEDED,
    "fail": Payment.Status.FAILED,
    "refund": Payment.Status.REFUNDED,
}

TRANSACTION_STATUSES = {
    "AwaitingAuthentication": Payment.Status.PROCESSING,
    "Authorized": Payment.Status.PROCESSING,
    "Completed": Payment.Status.SUCCEEDED,
    "Cancelled": Payment.Status.CANCELED,
    "Declined": Payment.Status.FAILED,
}

# The card token charges the card again with our credentials, so it is not kept.
UNSTORED_FIELDS = {"Token"}


@dataclass(frozen=True)
class CloudPaymentsProvider(PaymentProvider):
    code = Payment.Provider.CLOUDPAYMENTS.value
    title = "Банковская карта"
    pay_label = "Оплатить картой"

    public_id: str
    api_secret: str
    api_url: str
    timeout: int
    order_ttl_minutes: int
    receipts_enabled: bool
    taxation_system: int
    vat: int | None
    receipt_method: int
    receipt_object: int

    @classmethod
    def from_settings(cls) -> "CloudPaymentsProvider":
        return cls(
            public_id=settings.CLOUDPAYMENTS_PUBLIC_ID,
            api_secret=settings.CLOUDPAYMENTS_API_SECRET,
            api_url=settings.CLOUDPAYMENTS_API_URL,
            timeout=settings.CLOUDPAYMENTS_API_TIMEOUT,
            order_ttl_minutes=settings.CLOUDPAYMENTS_ORDER_TTL_MINUTES,
            receipts_enabled=settings.CLOUDPAYMENTS_RECEIPTS_ENABLED,
            taxation_system=settings.CLOUDPAYMENTS_TAXATION_SYSTEM,
            vat=settings.CLOUDPAYMENTS_VAT,
            receipt_method=settings.CLOUDPAYMENTS_RECEIPT_METHOD,
            receipt_object=settings.CLOUDPAYMENTS_RECEIPT_OBJECT,
        )

    def is_enabled(self) -> bool:
        credentials = (self.public_id, self.api_secret)
        return all(credentials) and not any(PLACEHOLDER_MARK in value for value in credentials)

    def supports(self, amount_rub) -> bool:
        return amount_rub > 0

    def create_checkout(self, payment, *, success_url: str, fail_url: str, webhook_url: str) -> CheckoutSession:
        # Notification URLs are set once in the CloudPayments dashboard, so webhook_url is not sent.
        description = payment.product_snapshot.get("description") or payment.get_purpose_display()
        email = payment.user.email
        body = {
            "Amount": float(payment.amount),
            "Currency": payment.currency,
            "Description": description,
            "InvoiceId": str(payment.public_id),
            "AccountId": str(payment.user_id),
            "RequireConfirmation": False,
            "SendEmail": False,
            "SuccessRedirectUrl": success_url,
            "FailRedirectUrl": fail_url,
        }
        if email:
            body["Email"] = email
        if self.receipts_enabled:
            body["JsonData"] = {"CloudPayments": {"CustomerReceipt": self._receipt(payment, description, email)}}

        answer = self._call("orders/create", body)
        order = answer.get("Model") or {}
        if not answer.get("Success") or not order.get("Url"):
            logger.error("CloudPayments did not create an order for payment %s: %s", payment.public_id, answer.get("Message"))
            raise PaymentProviderError("Не удалось создать оплату. Попробуйте позже.")
        return CheckoutSession(
            redirect_url=order["Url"],
            external_invoice_id=str(order.get("Id", "")),
            expires_at=timezone.now() + timedelta(minutes=self.order_ttl_minutes),
        )

    def verify_signature(self, request) -> None:
        received = request.headers.get("Content-HMAC", "")
        expected = base64.b64encode(hmac.new(self.api_secret.encode(), request.body, hashlib.sha256).digest())
        if not received or not hmac.compare_digest(received.encode(), expected):
            raise InvalidSignature("CloudPayments: неверная подпись уведомления.")

    def parse_webhook(self, request, *, event_type: str) -> ProviderEvent:
        status = NOTIFICATION_STATUSES.get(event_type)
        if status is None:
            raise PaymentProviderError(f"CloudPayments: неизвестное уведомление «{event_type}».")
        data = _notification_data(request)
        if event_type == "pay" and data.get("Status") == "Authorized":
            status = Payment.Status.PROCESSING
        return _event(event_type, status, data)

    def fetch_status(self, payment) -> ProviderEvent | None:
        answer = self._call("v2/payments/find", {"InvoiceId": str(payment.public_id)})
        transaction = answer.get("Model")
        if not answer.get("Success") or not transaction:
            return None
        status = TRANSACTION_STATUSES.get(transaction.get("Status"))
        if status is None:
            return None
        return _event("reconcile", status, transaction)

    def webhook_response(self, *, rejection: Rejection | None = None):
        return JsonResponse({"code": REJECTION_CODES.get(rejection, 0)})

    def _receipt(self, payment, description: str, email: str) -> dict:
        amount = float(payment.amount)
        receipt = {
            "Items": [
                {
                    "label": description[:128],
                    "price": amount,
                    "quantity": 1,
                    "amount": amount,
                    "vat": self.vat,
                    "method": self.receipt_method,
                    "object": self.receipt_object,
                }
            ],
            "taxationSystem": self.taxation_system,
            "amounts": {"electronic": amount},
        }
        if email:
            receipt["email"] = email
        return receipt

    def _call(self, endpoint: str, body: dict) -> dict:
        credentials = base64.b64encode(f"{self.public_id}:{self.api_secret}".encode()).decode()
        request = Request(
            f"{self.api_url}/{endpoint}",
            data=json.dumps(body).encode(),
            method="POST",
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                answer = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            logger.error("CloudPayments %s answered HTTP %s", endpoint, error.code)
            raise PaymentProviderError("Платёжный сервис временно недоступен.") from error
        except (URLError, TimeoutError, ValueError) as error:
            logger.error("CloudPayments %s failed: %s", endpoint, error)
            raise PaymentProviderError("Платёжный сервис временно недоступен.") from error
        if not isinstance(answer, dict):
            raise PaymentProviderError("CloudPayments: неожиданный ответ.")
        return answer


def _notification_data(request) -> dict:
    # Notifications are form-encoded unless JSON is switched on in the dashboard.
    if request.content_type != "application/json":
        return request.POST.dict()
    try:
        data = json.loads(request.body)
    except ValueError as error:
        raise PaymentProviderError("CloudPayments: тело уведомления не JSON.") from error
    if not isinstance(data, dict):
        raise PaymentProviderError("CloudPayments: тело уведомления не объект.")
    return data


def _event(event_type: str, status: str, data: dict) -> ProviderEvent:
    transaction_id = str(data.get("TransactionId") or "").strip()
    if not transaction_id:
        raise PaymentProviderError("CloudPayments: нет TransactionId.")
    account_id = data.get("AccountId")
    reason = str(data.get("Reason") or "")
    if reason and data.get("ReasonCode") not in (None, ""):
        reason = f"{reason} ({data['ReasonCode']})"
    dedup_key = f"{event_type}:{transaction_id}"
    if event_type == "reconcile":
        dedup_key = f"{dedup_key}:{data.get('Status')}"
    return ProviderEvent(
        event_type=event_type,
        payment_public_id=str(data.get("InvoiceId") or ""),
        status=status,
        external_id=transaction_id,
        amount=_decimal(data.get("Amount")),
        currency=str(data.get("Currency") or ""),
        paid_amount=_decimal(data.get("PaymentAmount")),
        paid_currency=str(data.get("PaymentCurrency") or ""),
        is_test=str(data.get("TestMode", "")).strip().lower() in {"1", "true"},
        account_id=None if account_id is None else str(account_id),
        dedup_key=dedup_key,
        failure_reason=reason[:255],
        raw={key: value for key, value in data.items() if key not in UNSTORED_FIELDS},
    )


def _decimal(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        amount = Decimal(str(value))
    except InvalidOperation as error:
        raise PaymentProviderError(f"CloudPayments: неверная сумма «{value}».") from error
    if not amount.is_finite():
        raise PaymentProviderError(f"CloudPayments: неверная сумма «{value}».")
    return amount
