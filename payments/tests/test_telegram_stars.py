from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cabinet.models import User
from payments.models import Payment
from payments.services.providers.telegram_stars import TelegramStarsProvider
from payments.services.telegram_stars import answer_pre_checkout_query, record_successful_payment
from payments.tests.test_cloudpayments import CLOUDPAYMENTS_SETTINGS
from payments.tests.test_models import TEST_STORAGES, make_payment
from payments.utils import build_payment_options
from wallets.models import CoinPackage, CoinTransaction

STARS_SETTINGS = {
    "PAYMENTS_ENABLED_PROVIDERS": ["telegram_stars"],
    "PAYMENTS_ALLOW_TEST_PAYMENTS": False,
    "PAYMENTS_STAFF_ONLY": False,
    "TG_BOT_TOKEN": "123456:TEST-STARS",
    "TELEGRAM_STARS_RUB_RATE": Decimal("1.5"),
    "TELEGRAM_STARS_ORDER_TTL_MINUTES": 60,
}
INVOICE_URL = "https://t.me/$test-invoice"
# 499 ₽ at 1.5 ₽ per Star, rounded up.
STARS = 333


@override_settings(STORAGES=TEST_STORAGES, **STARS_SETTINGS)
class TelegramStarsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="stars-buyer", password="safe-test-password")
        self.package = CoinPackage.objects.create(title="Старт", coins=1000, bonus_coins=100, price_rub=Decimal("499.00"))
        cache.delete(f"ratelimit:payments:checkout:{self.user.pk}")

    def stars_payment(self, **extra):
        values = {
            "provider": Payment.Provider.TELEGRAM_STARS,
            "status": Payment.Status.PENDING,
            "coin_package": self.package,
            "product_snapshot": {
                "package_id": self.package.pk,
                "title": "Старт",
                "coins": 1000,
                "bonus_coins": 100,
                "price_rub": "499.00",
            },
            "expires_at": timezone.now() + timedelta(minutes=30),
        }
        values.update(extra)
        return make_payment(self.user, **values)

    def pre_checkout(self, payment, *, total_amount=STARS):
        query = {
            "id": "query-1",
            "currency": "XTR",
            "total_amount": total_amount,
            "invoice_payload": f"{payment.public_id}:{STARS}",
        }
        with patch("notifications.telegram_bot.api_call") as api_call:
            answer_pre_checkout_query(query)
        return api_call.call_args.args

    def successful_payment(self, payment, *, charge_id="charge-1"):
        # Delivery starts after the transaction commits.
        with self.captureOnCommitCallbacks(execute=True):
            record_successful_payment(
                {
                    "currency": "XTR",
                    "total_amount": STARS,
                    "invoice_payload": f"{payment.public_id}:{STARS}",
                    "telegram_payment_charge_id": charge_id,
                    "provider_payment_charge_id": "",
                }
            )

    def test_price_in_stars_rounds_up(self):
        provider = TelegramStarsProvider.from_settings()

        self.assertEqual(provider.stars_for(Decimal("499.00")), STARS)
        self.assertEqual(provider.stars_for(Decimal("0.10")), 1)

    def test_mini_app_checkout_returns_the_invoice_link(self):
        self.client.force_login(self.user)
        with patch("notifications.telegram_bot.api_call", return_value=INVOICE_URL) as api_call:
            response = self.client.post(
                reverse("payments:checkout", args=["coin_package"]),
                {"provider": "telegram_stars", "package_id": self.package.pk},
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )

        payment = Payment.objects.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "ok": True,
                "checkout_url": INVOICE_URL,
                "return_url": reverse("payments:return", args=[payment.public_id]),
            },
        )
        self.assertEqual(payment.status, Payment.Status.PENDING)
        method, invoice = api_call.call_args.args
        self.assertEqual(method, "createInvoiceLink")
        self.assertEqual(invoice["currency"], "XTR")
        self.assertEqual(invoice["payload"], f"{payment.public_id}:{STARS}")
        self.assertEqual(invoice["prices"][0]["amount"], STARS)
        self.assertLessEqual(len(invoice["title"]), 32)

    def test_checkout_error_is_json_for_the_mini_app(self):
        self.client.force_login(self.user)
        with patch("notifications.telegram_bot.api_call", side_effect=RuntimeError("Bad Request")):
            response = self.client.post(
                reverse("payments:checkout", args=["coin_package"]),
                {"provider": "telegram_stars", "package_id": self.package.pk},
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])
        self.assertEqual(Payment.objects.get().status, Payment.Status.FAILED)

    def test_open_order_is_accepted_before_payment(self):
        payment = self.stars_payment()

        method, answer = self.pre_checkout(payment)

        self.assertEqual(method, "answerPreCheckoutQuery")
        self.assertEqual(answer, {"pre_checkout_query_id": "query-1", "ok": True})

    def test_expired_order_is_refused_before_payment(self):
        payment = self.stars_payment(expires_at=timezone.now() - timedelta(minutes=1))

        _, answer = self.pre_checkout(payment)

        self.assertFalse(answer["ok"])
        self.assertIn("Срок оплаты истёк", answer["error_message"])

    def test_amount_other_than_invoiced_is_refused(self):
        payment = self.stars_payment()

        _, answer = self.pre_checkout(payment, total_amount=STARS - 1)

        self.assertFalse(answer["ok"])

    def test_paid_stars_deliver_the_coins_once(self):
        payment = self.stars_payment()

        self.successful_payment(payment)
        self.successful_payment(payment)

        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.SUCCEEDED)
        self.assertEqual(payment.external_id, "charge-1")
        self.assertEqual(payment.paid_amount, Decimal(STARS))
        self.assertEqual(payment.paid_currency, "XTR")
        self.assertIsNotNone(payment.fulfilled_at)
        purchases = CoinTransaction.objects.filter(
            user=self.user,
            kind=CoinTransaction.Kind.PACKAGE_PURCHASE,
            related_model="payments.payment",
            related_id=payment.pk,
        )
        self.assertEqual([t.amount for t in purchases], [1100])

    @override_settings(
        **{**CLOUDPAYMENTS_SETTINGS, **STARS_SETTINGS, "PAYMENTS_ENABLED_PROVIDERS": ["cloudpayments", "telegram_stars"]}
    )
    def test_stars_only_in_the_mini_app_and_cards_only_on_the_site(self):
        site = build_payment_options(Decimal("499.00"), self.user)
        mini_app = build_payment_options(Decimal("499.00"), self.user, in_telegram_app=True)

        self.assertEqual([option["code"] for option in site], ["cloudpayments"])
        self.assertEqual([option["code"] for option in mini_app], ["telegram_stars"])

    def test_webhook_endpoint_does_not_take_stars(self):
        response = self.client.post(reverse("payments:webhook", args=["telegram_stars", "ipn"]), data="{}", content_type="application/json")

        self.assertEqual(response.status_code, 400)


class StarsBotRoutingTests(TestCase):
    def test_bot_passes_stars_updates_to_payments(self):
        from notifications.management.commands.run_telegram_bot import Command

        target = "notifications.management.commands.run_telegram_bot"
        with patch(f"{target}.answer_pre_checkout_query") as answer, patch(f"{target}.record_successful_payment") as record:
            Command()._handle_update({"pre_checkout_query": {"id": "query-1"}})
            Command()._handle_update({"message": {"chat": {"type": "private"}, "successful_payment": {"total_amount": 1}}})

        answer.assert_called_once_with({"id": "query-1"})
        record.assert_called_once_with({"total_amount": 1})
