import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.messages import get_messages
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cabinet.models import AnalystPaidPlan, AnalystProfile, User, UserVipSubscription, VipPlan
from payments.models import Payment
from payments.tests.test_cloudpayments import CLOUDPAYMENTS_SETTINGS, api_answer
from payments.tests.test_models import TEST_STORAGES, make_payment
from wallets.models import CoinPackage

ORDER_CREATED = {"Success": True, "Model": {"Id": "order-1", "Url": "https://orders.cloudpayments.ru/d/order-1"}}


@override_settings(STORAGES=TEST_STORAGES, **CLOUDPAYMENTS_SETTINGS)
class CheckoutTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="checkout-buyer", password="safe-test-password", email="buyer@example.com")
        self.analyst = User.objects.create_user(
            username="checkout-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        AnalystProfile.objects.filter(user=self.analyst).update(paid_predictions_enabled=True)
        self.package = CoinPackage.objects.create(title="Старт", coins=1000, bonus_coins=100, price_rub=Decimal("499.00"))
        cache.delete(f"ratelimit:payments:checkout:{self.user.pk}")
        cache.delete(f"ratelimit:payments:checkout:{self.analyst.pk}")
        self.client.force_login(self.user)

    def checkout(self, purpose, data, *, answer=ORDER_CREATED):
        with patch("payments.services.providers.cloudpayments.urlopen", return_value=api_answer(answer)) as urlopen:
            response = self.client.post(
                reverse("payments:checkout", args=[purpose]),
                {"provider": "cloudpayments", **data},
            )
        return response, urlopen

    def error(self, response):
        # Messages pile up in the cookie because the redirects are not followed.
        return [str(message) for message in get_messages(response.wsgi_request)][-1]

    def test_coin_package_order_sends_the_payer_to_the_provider(self):
        response, urlopen = self.checkout("coin_package", {"package_id": self.package.pk})

        payment = Payment.objects.get()
        self.assertRedirects(response, "https://orders.cloudpayments.ru/d/order-1", fetch_redirect_response=False)
        self.assertEqual(payment.status, Payment.Status.PENDING)
        self.assertEqual(payment.amount, Decimal("499.00"))
        self.assertEqual(payment.coin_package, self.package)
        self.assertEqual(payment.external_invoice_id, "order-1")
        self.assertIsNotNone(payment.expires_at)
        self.assertEqual(
            payment.product_snapshot,
            {
                "package_id": self.package.pk,
                "title": "Старт",
                "coins": 1000,
                "bonus_coins": 100,
                "price_rub": "499.00",
                "description": "Пакет коинов «Старт»",
            },
        )
        body = json.loads(urlopen.call_args.args[0].data)
        self.assertEqual(body["SuccessRedirectUrl"], f"http://testserver/payments/{payment.public_id}/return/")
        self.assertEqual(body["Description"], "Пакет коинов «Старт»")

    def test_asking_again_reuses_the_open_order(self):
        self.checkout("coin_package", {"package_id": self.package.pk})
        response, urlopen = self.checkout("coin_package", {"package_id": self.package.pk})

        self.assertEqual(Payment.objects.count(), 1)
        urlopen.assert_not_called()
        self.assertRedirects(response, "https://orders.cloudpayments.ru/d/order-1", fetch_redirect_response=False)

    def test_open_orders_are_limited(self):
        for _ in range(5):
            make_payment(self.user, status=Payment.Status.PENDING, expires_at=timezone.now() + timedelta(hours=1))

        response, urlopen = self.checkout("coin_package", {"package_id": self.package.pk})

        urlopen.assert_not_called()
        self.assertRedirects(response, reverse("wallets:top_up"), fetch_redirect_response=False)
        self.assertIn("Слишком много неоплаченных заказов", self.error(response))

    def test_provider_failure_closes_the_order(self):
        with self.assertLogs("payments", "ERROR"):
            response, _ = self.checkout("coin_package", {"package_id": self.package.pk}, answer={"Success": False})

        self.assertEqual(Payment.objects.get().status, Payment.Status.FAILED)
        self.assertRedirects(response, reverse("wallets:top_up"), fetch_redirect_response=False)
        self.assertEqual(self.error(response), "Не удалось создать оплату. Попробуйте позже.")

    def test_unavailable_products_and_methods_are_refused(self):
        CoinPackage.objects.filter(pk=self.package.pk).update(is_active=False)
        response, _ = self.checkout("coin_package", {"package_id": self.package.pk})
        self.assertEqual(self.error(response), "Этот пакет коинов больше недоступен.")

        with override_settings(PAYMENTS_ENABLED_PROVIDERS=[]):
            response, _ = self.checkout("coin_package", {"package_id": "abc"})
        self.assertEqual(self.error(response), "Этот пакет коинов больше недоступен.")

        CoinPackage.objects.filter(pk=self.package.pk).update(is_active=True)
        with override_settings(PAYMENTS_ENABLED_PROVIDERS=[]):
            response, _ = self.checkout("coin_package", {"package_id": self.package.pk})
        self.assertEqual(self.error(response), "Этот способ оплаты сейчас недоступен.")
        self.assertFalse(Payment.objects.exists())
        self.assertEqual(self.client.post(reverse("payments:checkout", args=["donation"])).status_code, 404)

    def test_checkout_attempts_are_rate_limited(self):
        with patch("payments.views.CHECKOUT_ATTEMPTS_LIMIT", 1):
            self.checkout("coin_package", {"package_id": self.package.pk})
            response, urlopen = self.checkout("coin_package", {"package_id": self.package.pk})

        urlopen.assert_not_called()
        self.assertIn("Слишком много попыток", self.error(response))

    def test_subscription_order_fixes_the_plan_and_the_platform_fee(self):
        plan = AnalystPaidPlan.objects.create(analyst=self.analyst, title="Месяц", duration_days=30, price=Decimal("990.00"))

        response, _ = self.checkout("paid_subscription", {"analyst_id": self.analyst.pk, "plan_id": plan.pk})

        payment = Payment.objects.get()
        self.assertEqual(payment.paid_plan, plan)
        self.assertEqual(payment.product_snapshot["analyst_id"], self.analyst.pk)
        self.assertEqual(payment.product_snapshot["plan_id"], plan.pk)
        self.assertEqual(payment.product_snapshot["duration_days"], 30)
        self.assertEqual(payment.product_snapshot["price_rub"], "990.00")
        self.assertIn("platform_fee_percent", payment.product_snapshot)
        self.assertEqual(payment.product_snapshot["description"], "Подписка на прогнозы @checkout-capper: Месяц")

        self.client.force_login(self.analyst)
        response, _ = self.checkout("paid_subscription", {"analyst_id": self.analyst.pk, "plan_id": plan.pk})
        self.assertEqual(self.error(response), "Нельзя оформить платную подписку на самого себя.")
        self.assertRedirects(
            response,
            reverse("cabinet:paid_predictions_subscribe", args=[self.analyst.pk]),
            fetch_redirect_response=False,
        )

    def test_vip_order_needs_a_capper_and_a_confirmed_switch(self):
        monthly = VipPlan.objects.create(title="VIP 30", duration_days=30, price_rub=Decimal("300"))
        weekly = VipPlan.objects.create(title="VIP 7", duration_days=7, price_rub=Decimal("100"))

        response, _ = self.checkout("vip_plan", {"plan_id": weekly.pk})
        self.assertEqual(self.error(response), "VIP-тарифы доступны только капперам.")

        self.client.force_login(self.analyst)
        UserVipSubscription.objects.create(
            user=self.analyst,
            plan=monthly,
            starts_at=timezone.now(),
            ends_at=timezone.now() + timedelta(days=20),
            duration_days=30,
        )
        response, _ = self.checkout("vip_plan", {"plan_id": weekly.pk})
        self.assertIn("Подтвердите переход", self.error(response))

        self.checkout("vip_plan", {"plan_id": weekly.pk, "purchase_mode": "switch"})
        payment = Payment.objects.get()
        self.assertEqual(payment.vip_plan, weekly)
        self.assertEqual(
            payment.product_snapshot,
            {
                "plan_id": weekly.pk,
                "title": "VIP 7",
                "duration_days": 7,
                "price_rub": "100.00",
                "switch": True,
                "description": "VIP-тариф «VIP 7» на 7 дн.",
            },
        )


@override_settings(STORAGES=TEST_STORAGES, **CLOUDPAYMENTS_SETTINGS)
class PaymentReturnTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="return-buyer", password="safe-test-password")
        self.payment = make_payment(
            self.user,
            status=Payment.Status.PENDING,
            expires_at=timezone.now() + timedelta(hours=1),
            checkout_url="https://orders.cloudpayments.ru/d/order-1",
            product_snapshot={"description": "Пакет коинов «Старт»"},
        )
        self.client.force_login(self.user)

    def status(self):
        return self.client.get(reverse("payments:status", args=[self.payment.public_id])).json()

    def test_return_page_shows_the_order_and_polls_its_status(self):
        page = self.client.get(reverse("payments:return", args=[self.payment.public_id]))

        self.assertContains(page, "Пакет коинов «Старт»")
        self.assertContains(page, "Ждём подтверждение оплаты")
        self.assertContains(page, f'data-payment-status-url="/payments/{self.payment.public_id}/status/"')
        self.assertContains(page, 'href="/wallets/top-up/"')

    def test_status_follows_the_payment(self):
        self.assertEqual(self.status()["state"], "pending")

        Payment.objects.filter(pk=self.payment.pk).update(status=Payment.Status.FAILED)
        failed = self.status()
        self.assertEqual(failed["state"], "failed")
        self.assertEqual(failed["retry_url"], "https://orders.cloudpayments.ru/d/order-1")

        Payment.objects.filter(pk=self.payment.pk).update(status=Payment.Status.SUCCEEDED)
        self.assertEqual(self.status()["title"], "Оплата получена")

        Payment.objects.filter(pk=self.payment.pk).update(fulfilled_at=timezone.now())
        self.assertEqual(self.status(), {
            "state": "done",
            "title": "Оплата прошла",
            "text": "Коины зачислены на баланс.",
            "retry_url": "",
        })

    def test_only_the_payer_sees_the_payment(self):
        self.client.force_login(User.objects.create_user(username="return-stranger", password="safe-test-password"))

        self.assertEqual(self.client.get(reverse("payments:return", args=[self.payment.public_id])).status_code, 404)
        self.assertEqual(self.client.get(reverse("payments:status", args=[self.payment.public_id])).status_code, 404)


@override_settings(STORAGES=TEST_STORAGES, **CLOUDPAYMENTS_SETTINGS)
class PayButtonTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="buttons-buyer", password="safe-test-password")
        self.analyst = User.objects.create_user(
            username="buttons-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        AnalystProfile.objects.filter(user=self.analyst).update(paid_predictions_enabled=True)
        CoinPackage.objects.create(title="Старт", coins=1000, bonus_coins=100, price_rub=Decimal("499.00"))

    def test_coin_packages_offer_card_payment_only_when_it_is_on(self):
        self.client.force_login(self.user)

        page = self.client.get(reverse("wallets:top_up"))
        self.assertContains(page, 'formaction="/payments/checkout/coin_package/"')
        self.assertContains(page, "Оплатить картой")
        self.assertNotContains(page, "Выбрать пакет")

        with override_settings(PAYMENTS_ENABLED_PROVIDERS=[]):
            page = self.client.get(reverse("wallets:top_up"))
        self.assertNotContains(page, "Оплатить картой")
        self.assertContains(page, "Выбрать пакет")

    def test_plans_the_balance_does_not_cover_can_be_paid_by_card(self):
        plan = AnalystPaidPlan.objects.create(analyst=self.analyst, title="Месяц", duration_days=30, price=Decimal("990.00"))
        self.client.force_login(self.user)

        page = self.client.get(reverse("cabinet:paid_predictions_subscribe", args=[self.analyst.pk]))

        self.assertContains(page, f'name="plan_id" value="{plan.pk}" checked>')
        self.assertContains(page, "Недостаточно средств на балансе")
        self.assertContains(page, "Оплатить с баланса</button>")
        self.assertContains(page, 'formaction="/payments/checkout/paid_subscription/"')
        self.assertContains(page, f'name="analyst_id" value="{self.analyst.pk}"')

    def test_vip_switch_by_card_goes_through_the_warning_dialog(self):
        monthly = VipPlan.objects.create(title="VIP 30", duration_days=30, price_rub=Decimal("300"))
        VipPlan.objects.create(title="VIP 7", duration_days=7, price_rub=Decimal("100"))
        UserVipSubscription.objects.create(
            user=self.analyst,
            plan=monthly,
            starts_at=timezone.now(),
            ends_at=timezone.now() + timedelta(days=20),
            duration_days=30,
        )
        self.client.force_login(self.analyst)

        page = self.client.get(reverse("cabinet:vip_plans"))

        # The current tariff is extended directly; the other one opens the switch dialog.
        self.assertContains(page, 'formaction="/payments/checkout/vip_plan/"', count=1)
        self.assertContains(page, 'data-vip-checkout-action="/payments/checkout/vip_plan/"', count=1)
        self.assertContains(page, 'data-vip-provider="cloudpayments"')
