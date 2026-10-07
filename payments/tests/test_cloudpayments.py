import base64
import hashlib
import hmac
import json
import uuid
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch
from urllib.parse import urlencode

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cabinet.models import User
from payments.models import Payment, PaymentEvent
from payments.services.providers.base import PaymentProviderDisabled, PaymentProviderError
from payments.services.providers.cloudpayments import CloudPaymentsProvider
from payments.services.providers.factory import PaymentProviderFactory
from payments.tests.test_models import TEST_STORAGES, make_payment


SECRET = "test-api-secret"
CLOUDPAYMENTS_SETTINGS = {
    "PAYMENTS_ENABLED_PROVIDERS": ["cloudpayments"],
    "PAYMENTS_ALLOW_TEST_PAYMENTS": False,
    "PAYMENTS_STAFF_ONLY": False,
    "CLOUDPAYMENTS_PUBLIC_ID": "pk_test",
    "CLOUDPAYMENTS_API_SECRET": SECRET,
    "CLOUDPAYMENTS_API_URL": "https://api.cloudpayments.test",
    "CLOUDPAYMENTS_RECEIPTS_ENABLED": True,
    "CLOUDPAYMENTS_TAXATION_SYSTEM": 1,
    "CLOUDPAYMENTS_VAT": None,
    "CLOUDPAYMENTS_RECEIPT_METHOD": 4,
    "CLOUDPAYMENTS_RECEIPT_OBJECT": 4,
}


def api_answer(payload):
    response = MagicMock()
    response.read.return_value = json.dumps(payload).encode()
    response.__enter__.return_value = response
    return response


def post_notification(client, event_type, fields, *, as_json=False, signature=None):
    if as_json:
        body, content_type = json.dumps(fields).encode(), "application/json"
    else:
        body, content_type = urlencode(fields).encode(), "application/x-www-form-urlencoded"
    if signature is None:
        signature = base64.b64encode(hmac.new(SECRET.encode(), body, hashlib.sha256).digest()).decode()
    return client.post(
        reverse("payments:webhook", args=["cloudpayments", event_type]),
        data=body,
        content_type=content_type,
        headers={"Content-HMAC": signature},
    )


@override_settings(**CLOUDPAYMENTS_SETTINGS)
class CloudPaymentsApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="cp-payer", password="safe-test-password", email="payer@example.com")
        self.payment = make_payment(self.user, status=Payment.Status.PENDING, product_snapshot={"description": "Пакет «Старт»"})

    def _checkout(self, answer):
        provider = PaymentProviderFactory.create("cloudpayments")
        with patch("payments.services.providers.cloudpayments.urlopen", return_value=api_answer(answer)) as urlopen:
            session = provider.create_checkout(
                self.payment,
                success_url="https://site.test/ok/",
                fail_url="https://site.test/fail/",
                webhook_url="",
            )
        request = urlopen.call_args.args[0]
        return session, request, json.loads(request.data)

    def test_order_is_created_with_a_receipt(self):
        session, request, body = self._checkout(
            {"Success": True, "Model": {"Id": "order-1", "Url": "https://orders.cloudpayments.ru/d/order-1"}}
        )

        self.assertEqual(request.full_url, "https://api.cloudpayments.test/orders/create")
        self.assertEqual(request.get_header("Authorization"), "Basic " + base64.b64encode(f"pk_test:{SECRET}".encode()).decode())
        self.assertEqual(body["InvoiceId"], str(self.payment.public_id))
        self.assertEqual(body["AccountId"], str(self.user.pk))
        self.assertEqual(body["Amount"], 499.0)
        self.assertEqual(body["Description"], "Пакет «Старт»")
        receipt = body["JsonData"]["CloudPayments"]["CustomerReceipt"]
        self.assertEqual(receipt["taxationSystem"], 1)
        self.assertEqual(receipt["email"], "payer@example.com")
        self.assertEqual(
            receipt["Items"],
            [{"label": "Пакет «Старт»", "price": 499.0, "quantity": 1, "amount": 499.0, "vat": None, "method": 4, "object": 4}],
        )
        self.assertEqual(session.redirect_url, "https://orders.cloudpayments.ru/d/order-1")
        self.assertEqual(session.external_invoice_id, "order-1")
        self.assertAlmostEqual(session.expires_at, timezone.now() + timedelta(minutes=60), delta=timedelta(minutes=1))

    @override_settings(CLOUDPAYMENTS_RECEIPTS_ENABLED=False)
    def test_receipt_is_not_sent_when_receipts_are_off(self):
        _, _, body = self._checkout({"Success": True, "Model": {"Id": "order-2", "Url": "https://orders.test/2"}})

        self.assertNotIn("JsonData", body)

    def test_refused_order_is_an_error(self):
        with self.assertRaises(PaymentProviderError), self.assertLogs("payments", "ERROR"):
            self._checkout({"Success": False, "Message": "Invalid amount"})

    def test_status_is_reconciled_by_invoice(self):
        found = {
            "Success": True,
            "Model": {
                "TransactionId": 1001,
                "InvoiceId": str(self.payment.public_id),
                "AccountId": str(self.user.pk),
                "Amount": 499.0,
                "Currency": "RUB",
                "Status": "Completed",
                "TestMode": False,
            },
        }
        provider = PaymentProviderFactory.create("cloudpayments")
        with patch("payments.services.providers.cloudpayments.urlopen", return_value=api_answer(found)) as urlopen:
            event = provider.fetch_status(self.payment)
        with patch("payments.services.providers.cloudpayments.urlopen", return_value=api_answer({"Success": False, "Message": "Not found"})):
            missing = provider.fetch_status(self.payment)

        self.assertEqual(urlopen.call_args.args[0].full_url, "https://api.cloudpayments.test/v2/payments/find")
        self.assertEqual(event.status, Payment.Status.SUCCEEDED)
        self.assertEqual(event.amount, Decimal("499"))
        self.assertEqual(event.dedup_key, "reconcile:1001:Completed")
        self.assertIsNone(missing)

    @override_settings(CLOUDPAYMENTS_API_SECRET="change-me-cloudpayments-api-secret")
    def test_placeholder_credentials_keep_the_provider_off(self):
        with self.assertRaises(PaymentProviderDisabled):
            PaymentProviderFactory.create("cloudpayments")
        self.assertIsInstance(CloudPaymentsProvider.from_settings(), CloudPaymentsProvider)


@override_settings(STORAGES=TEST_STORAGES, **CLOUDPAYMENTS_SETTINGS)
class CloudPaymentsWebhookTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="cp-webhook-payer", password="safe-test-password")
        self.payment = make_payment(
            self.user,
            status=Payment.Status.PENDING,
            expires_at=timezone.now() + timedelta(hours=1),
        )

    def fields(self, **extra):
        values = {
            "TransactionId": "1001",
            "Amount": "499.00",
            "Currency": "RUB",
            "PaymentAmount": "499.00",
            "PaymentCurrency": "RUB",
            "InvoiceId": str(self.payment.public_id),
            "AccountId": str(self.user.pk),
            "TestMode": "0",
            "Status": "Completed",
            "Token": "card-token",
        }
        values.update(extra)
        return values

    def notify(self, event_type, fields, **kwargs):
        return post_notification(self.client, event_type, fields, **kwargs)

    def code(self, event_type, fields, **kwargs):
        response = self.notify(event_type, fields, **kwargs)
        self.assertEqual(response.status_code, 200)
        return response.json()["code"]

    def test_check_accepts_a_payable_order(self):
        self.assertEqual(self.code("check", self.fields()), 0)

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PENDING)
        self.assertTrue(PaymentEvent.objects.filter(dedup_key="check:1001", payment=self.payment).exists())

    def test_check_refuses_with_the_reason_code(self):
        cases = [
            ("unknown order", {"InvoiceId": str(uuid.uuid4())}, 10),
            ("not a uuid", {"InvoiceId": "42"}, 10),
            ("another payer", {"AccountId": "999999"}, 11),
            ("wrong amount", {"Amount": "1.00"}, 12),
            ("wrong currency", {"Currency": "USD"}, 12),
            ("test payment", {"TestMode": "1"}, 13),
        ]
        for name, extra, code in cases:
            with self.subTest(name):
                self.assertEqual(self.code("check", self.fields(**extra)), code)

    def test_check_refuses_expired_and_paid_orders(self):
        Payment.objects.filter(pk=self.payment.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(self.code("check", self.fields()), 20)

        Payment.objects.filter(pk=self.payment.pk).update(expires_at=None, status=Payment.Status.SUCCEEDED)
        self.assertEqual(self.code("check", self.fields(TransactionId="1002")), 13)

    def test_pay_marks_the_payment_paid_once(self):
        self.assertEqual(self.code("pay", self.fields()), 0)
        self.payment.refresh_from_db()
        paid_at = self.payment.paid_at

        self.assertEqual(self.code("pay", self.fields()), 0)
        self.payment.refresh_from_db()

        self.assertEqual(self.payment.status, Payment.Status.SUCCEEDED)
        self.assertEqual(self.payment.external_id, "1001")
        self.assertEqual(self.payment.paid_amount, Decimal("499"))
        self.assertEqual(self.payment.paid_at, paid_at)
        self.assertFalse(self.payment.is_test)
        self.assertEqual(PaymentEvent.objects.filter(provider="cloudpayments", dedup_key="pay:1001").count(), 1)
        # The card token is never kept.
        self.assertNotIn("Token", self.payment.provider_payload)
        self.assertNotIn("Token", PaymentEvent.objects.get(dedup_key="pay:1001").payload)

    def test_json_notifications_are_accepted(self):
        fields = self.fields(TransactionId=1001, Amount=499.0, TestMode=False)

        self.assertEqual(self.code("pay", fields, as_json=True), 0)

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.SUCCEEDED)

    def test_declined_card_can_be_paid_again(self):
        self.code("fail", self.fields(TransactionId="1001", Reason="InsufficientFunds", ReasonCode="5051"))
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.FAILED)
        self.assertEqual(self.payment.failure_reason, "InsufficientFunds (5051)")

        self.code("pay", self.fields(TransactionId="1002"))
        self.payment.refresh_from_db()

        self.assertEqual(self.payment.status, Payment.Status.SUCCEEDED)
        self.assertEqual(self.payment.external_id, "1002")
        self.assertEqual(self.payment.failure_reason, "")

    def test_paid_payment_is_not_downgraded_by_a_late_failure(self):
        self.code("pay", self.fields(TransactionId="1001"))

        with self.assertLogs("payments", "WARNING"):
            self.assertEqual(self.code("fail", self.fields(TransactionId="1000", Reason="Timeout")), 0)

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.SUCCEEDED)
        self.assertIn("не меняется", PaymentEvent.objects.get(dedup_key="fail:1000").error)

    def test_full_refund_marks_the_payment_refunded(self):
        self.code("pay", self.fields())
        refund = {"TransactionId": "2001", "PaymentTransactionId": "1001", "Amount": "499.00", "InvoiceId": str(self.payment.public_id)}

        with self.assertLogs("payments", "ERROR"):
            self.code("refund", {**refund, "TransactionId": "2000", "Amount": "100.00"})
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.SUCCEEDED)

        self.code("refund", refund)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.REFUNDED)
        self.assertIsNotNone(self.payment.refunded_at)

    def test_payment_with_a_wrong_amount_is_logged_not_applied(self):
        with self.assertLogs("payments", "ERROR"):
            self.assertEqual(self.code("pay", self.fields(Amount="1.00")), 0)

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PENDING)
        self.assertIn("не совпадает", PaymentEvent.objects.get(dedup_key="pay:1001").error)

    def test_test_payments_need_to_be_allowed(self):
        with self.assertLogs("payments", "ERROR"):
            self.code("pay", self.fields(TestMode="1"))
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PENDING)

        with override_settings(PAYMENTS_ALLOW_TEST_PAYMENTS=True):
            self.code("pay", self.fields(TransactionId="1002", TestMode="1"))
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.SUCCEEDED)
        self.assertTrue(self.payment.is_test)

    def test_forged_notifications_are_refused(self):
        forged = base64.b64encode(hmac.new(b"other-secret", b"x", hashlib.sha256).digest()).decode()

        with self.assertLogs("payments", "WARNING"):
            self.assertEqual(self.notify("pay", self.fields(), signature=forged).status_code, 403)
            self.assertEqual(self.notify("pay", self.fields(), signature="").status_code, 403)

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PENDING)
        self.assertFalse(PaymentEvent.objects.exists())

    def test_only_signed_posts_of_known_notifications_reach_an_enabled_provider(self):
        url = reverse("payments:webhook", args=["cloudpayments", "pay"])
        self.assertEqual(self.client.get(url).status_code, 405)
        with self.assertLogs("payments", "WARNING"):
            self.assertEqual(self.notify("cancel", self.fields()).status_code, 400)
        with override_settings(PAYMENTS_ENABLED_PROVIDERS=[]):
            self.assertEqual(self.notify("pay", self.fields()).status_code, 404)
