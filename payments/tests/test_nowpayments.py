import hashlib
import hmac
import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cabinet.models import User
from payments.models import Payment, PaymentEvent
from payments.services.providers.base import PaymentProviderDisabled
from payments.services.providers.factory import PaymentProviderFactory
from payments.tasks import reconcile_pending_payments
from payments.tests.test_cloudpayments import api_answer
from payments.tests.test_models import TEST_STORAGES, make_payment
from wallets.models import CoinPackage, CoinTransaction

SECRET = "np-ipn-secret"
NOWPAYMENTS_SETTINGS = {
    "PAYMENTS_ENABLED_PROVIDERS": ["nowpayments"],
    "PAYMENTS_ALLOW_TEST_PAYMENTS": False,
    "PAYMENTS_STAFF_ONLY": False,
    "NOWPAYMENTS_API_KEY": "np-api-key",
    "NOWPAYMENTS_IPN_SECRET": SECRET,
    "NOWPAYMENTS_SANDBOX": False,
    "NOWPAYMENTS_API_TIMEOUT": 15,
    "NOWPAYMENTS_ORDER_TTL_MINUTES": 60,
    "NOWPAYMENTS_FEE_PAID_BY_USER": False,
    "NOWPAYMENTS_MIN_AMOUNT_RUB": 0,
}
COIN_TERMS = {
    "package_id": 1,
    "title": "Старт",
    "coins": 1000,
    "bonus_coins": 100,
    "price_rub": "499.00",
    "description": "Пакет коинов «Старт»",
}


def sign(payload):
    message = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(SECRET.encode(), message, hashlib.sha512).hexdigest()


def fake_api(answers):
    """urlopen stand-in answering by the API path, e.g. {"payment/77": {...}}."""

    def urlopen(request, timeout):
        path = request.full_url.split("/v1/", 1)[1]
        return api_answer(answers[path])

    return urlopen


@override_settings(STORAGES=TEST_STORAGES, **NOWPAYMENTS_SETTINGS)
class NOWPaymentsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="np-buyer", password="safe-test-password")
        cache.delete(f"ratelimit:payments:checkout:{self.user.pk}")
        self.payment = make_payment(
            self.user,
            provider=Payment.Provider.NOWPAYMENTS,
            status=Payment.Status.PENDING,
            expires_at=timezone.now() + timedelta(hours=1),
            product_snapshot=COIN_TERMS,
        )

    def api_payment(self, status, **extra):
        values = {
            "payment_id": 5077125051,
            "payment_status": status,
            "order_id": str(self.payment.public_id),
            "order_description": "Пакет коинов «Старт»",
            "price_amount": 499,
            "price_currency": "rub",
            "pay_amount": 0.0012,
            "actually_paid": 0.0012,
            "pay_currency": "btc",
        }
        values.update(extra)
        return values

    def notify(self, payload, *, signature=None, api=None):
        api = api or {"payment/5077125051": payload}
        with patch("payments.services.providers.http.urlopen", side_effect=fake_api(api)) as urlopen:
            response = self.client.post(
                reverse("payments:webhook", args=["nowpayments", "ipn"]),
                data=json.dumps(payload, ensure_ascii=False),
                content_type="application/json",
                headers={"x-nowpayments-sig": sign(payload) if signature is None else signature},
            )
        return response, urlopen

    def test_invoice_is_created_in_rubles_with_the_notification_address(self):
        package = CoinPackage.objects.create(title="Старт", coins=1000, bonus_coins=100, price_rub=Decimal("499.00"))
        invoice = {"id": "4522625843", "invoice_url": "https://nowpayments.io/payment/?iid=4522625843"}
        self.client.force_login(self.user)

        with patch("payments.services.providers.http.urlopen", side_effect=fake_api({"invoice": invoice})) as urlopen:
            response = self.client.post(
                reverse("payments:checkout", args=["coin_package"]),
                {"provider": "nowpayments", "package_id": package.pk},
            )

        payment = Payment.objects.get(coin_package=package)
        self.assertRedirects(response, invoice["invoice_url"], fetch_redirect_response=False)
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(payment.external_invoice_id, "4522625843")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.nowpayments.io/v1/invoice")
        self.assertEqual(request.get_header("X-api-key"), "np-api-key")
        body = json.loads(request.data)
        return_url = f"http://testserver/payments/{payment.public_id}/return/"
        self.assertEqual(
            body,
            {
                "price_amount": 499.0,
                "price_currency": "rub",
                "order_id": str(payment.public_id),
                "order_description": "Пакет коинов «Старт»",
                "ipn_callback_url": "http://testserver/payments/webhooks/nowpayments/ipn/",
                "success_url": return_url,
                "cancel_url": return_url,
                "is_fee_paid_by_user": False,
            },
        )

    @override_settings(NOWPAYMENTS_SANDBOX=True)
    def test_sandbox_uses_its_own_api(self):
        with patch("payments.services.providers.http.urlopen", side_effect=fake_api({"payment/77": self.api_payment("waiting")})) as urlopen:
            PaymentProviderFactory.create("nowpayments").fetch_status(
                make_payment(self.user, provider=Payment.Provider.NOWPAYMENTS, provider_payload={"payment_id": 77})
            )

        self.assertEqual(urlopen.call_args.args[0].full_url, "https://api-sandbox.nowpayments.io/v1/payment/77")

    def test_placeholder_keys_and_cheap_products_get_no_crypto(self):
        with override_settings(NOWPAYMENTS_IPN_SECRET="change-me-nowpayments-ipn-secret"), self.assertRaises(PaymentProviderDisabled):
            PaymentProviderFactory.create("nowpayments")

        with override_settings(NOWPAYMENTS_MIN_AMOUNT_RUB=300):
            self.assertEqual([p.code for p in PaymentProviderFactory.available_for(Decimal("299"))], [])
            self.assertEqual([p.code for p in PaymentProviderFactory.available_for(Decimal("300"))], ["nowpayments"])

    def test_finished_payment_is_confirmed_by_the_api_and_delivered(self):
        payload = self.api_payment(
            "finished",
            fee={"currency": "btc", "depositFee": 0.0001, "withdrawalFee": 0, "serviceFee": 0.00001},
        )

        with self.captureOnCommitCallbacks(execute=True):
            response, urlopen = self.notify(payload)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(urlopen.call_args.args[0].full_url, "https://api.nowpayments.io/v1/payment/5077125051")
        self.assertEqual(urlopen.call_args.args[0].get_method(), "GET")
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.SUCCEEDED)
        self.assertIsNotNone(self.payment.fulfilled_at)
        self.assertEqual(self.payment.external_id, "5077125051")
        self.assertEqual((self.payment.paid_amount, self.payment.paid_currency), (Decimal("0.0012"), "BTC"))
        self.assertFalse(self.payment.is_test)
        self.assertEqual(
            CoinTransaction.objects.filter(related_model="payments.payment", related_id=self.payment.pk).count(),
            1,
        )

    def test_status_comes_from_the_api_not_from_the_notification(self):
        payload = self.api_payment("finished")

        self.notify(payload, api={"payment/5077125051": self.api_payment("waiting")})

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PENDING)
        self.assertIsNone(self.payment.fulfilled_at)

    def test_partial_payment_is_not_delivered(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.notify(self.api_payment("partially_paid", actually_paid=0.0005))

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PARTIALLY_PAID)
        self.assertIsNone(self.payment.fulfilled_at)
        self.client.force_login(self.user)
        status = self.client.get(reverse("payments:status", args=[self.payment.public_id])).json()
        self.assertEqual(status["title"], "Оплачено не полностью")

    def test_wrong_amount_is_not_applied(self):
        with self.assertLogs("payments", "ERROR"):
            self.notify(self.api_payment("finished", price_amount=1))

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PENDING)

    def test_signature_made_by_javascript_is_accepted(self):
        # JSON.stringify keeps Cyrillic and writes 0.00001; Python would write 1e-05.
        body = (
            '{"actually_paid":0.0012,"fee":{"currency":"btc","depositFee":0,"serviceFee":0.00001},'
            '"order_description":"Пакет коинов «Старт»","order_id":"%s","pay_currency":"btc",'
            '"payment_id":5077125051,"payment_status":"finished","price_amount":499,"price_currency":"rub"}'
        ) % self.payment.public_id
        signature = hmac.new(SECRET.encode(), body.encode(), hashlib.sha512).hexdigest()
        api = {"payment/5077125051": self.api_payment("finished")}

        with patch("payments.services.providers.http.urlopen", side_effect=fake_api(api)):
            response = self.client.post(
                reverse("payments:webhook", args=["nowpayments", "ipn"]),
                data=body.encode(),
                content_type="application/json",
                headers={"x-nowpayments-sig": signature},
            )

        self.assertEqual(response.status_code, 200)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.SUCCEEDED)

    def test_forged_notifications_never_reach_the_api(self):
        payload = self.api_payment("finished")

        with self.assertLogs("payments", "WARNING"):
            forged, forged_api = self.notify(payload, signature="0" * 128)
            unsigned, unsigned_api = self.notify(payload, signature="")

        self.assertEqual((forged.status_code, unsigned.status_code), (403, 403))
        forged_api.assert_not_called()
        unsigned_api.assert_not_called()
        self.assertFalse(PaymentEvent.objects.exists())

    def test_repeated_notification_changes_nothing(self):
        payload = self.api_payment("confirming")

        self.notify(payload)
        self.notify(payload)

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PROCESSING)
        self.assertEqual(PaymentEvent.objects.filter(dedup_key="ipn:5077125051:confirming").count(), 1)

    @override_settings(NOWPAYMENTS_SANDBOX=True)
    def test_sandbox_payments_need_test_payments_allowed(self):
        payload = self.api_payment("finished")

        with self.assertLogs("payments", "ERROR"):
            self.notify(payload)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.PENDING)

        with override_settings(PAYMENTS_ALLOW_TEST_PAYMENTS=True):
            self.notify(self.api_payment("finished", payment_id=5077125052), api={"payment/5077125052": self.api_payment("finished", payment_id=5077125052)})
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.SUCCEEDED)
        self.assertTrue(self.payment.is_test)

    def test_reconciliation_asks_about_the_notified_payment(self):
        old = timezone.now() - timedelta(minutes=20)
        Payment.objects.filter(pk=self.payment.pk).update(created_at=old, provider_payload={"payment_id": 5077125051})
        silent = make_payment(self.user, provider=Payment.Provider.NOWPAYMENTS, status=Payment.Status.PENDING)
        Payment.objects.filter(pk=silent.pk).update(created_at=old)

        with (
            patch("payments.services.providers.http.urlopen", side_effect=fake_api({"payment/5077125051": self.api_payment("finished")})) as urlopen,
            self.captureOnCommitCallbacks(execute=True),
        ):
            reconcile_pending_payments()

        # The order nobody has paid has no NOWPayments payment to ask about yet.
        self.assertEqual(urlopen.call_count, 1)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, Payment.Status.SUCCEEDED)
        self.assertIsNotNone(self.payment.fulfilled_at)
