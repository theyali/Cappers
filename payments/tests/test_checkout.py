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
        with patch("payments.services.providers.http.urlopen", return_value=api_answer(answer)) as urlopen:
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

    @override_settings(PAYMENTS_STAFF_ONLY=True)
    def test_staff_only_launch_refuses_everyone_else(self):
        response, urlopen = self.checkout("coin_package", {"package_id": self.package.pk})

        urlopen.assert_not_called()
        self.assertEqual(self.error(response), "Этот способ оплаты сейчас недоступен.")
        self.assertFalse(Payment.objects.exists())

        User.objects.filter(pk=self.user.pk).update(is_staff=True)
        self.checkout("coin_package", {"package_id": self.package.pk})
        self.assertEqual(Payment.objects.get().status, Payment.Status.PENDING)

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

    @override_settings(PAYMENTS_STAFF_ONLY=True)
    def test_staff_only_launch_shows_card_payment_to_staff_alone(self):
        self.client.force_login(self.user)
        self.assertNotContains(self.client.get(reverse("wallets:top_up")), "Оплатить картой")

        User.objects.filter(pk=self.user.pk).update(is_staff=True)
        self.assertContains(self.client.get(reverse("wallets:top_up")), "Оплатить картой")

    def test_subscription_modal_reader_pays_directly_without_balance_option(self):
        plan = AnalystPaidPlan.objects.create(analyst=self.analyst, title="Месяц", duration_days=30, price=Decimal("990.00"))
        self.client.force_login(self.user)
        page = self.client.get(
            reverse("cabinet:paid_predictions_subscribe", args=[self.analyst.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertContains(page, f'name="plan_id" value="{plan.pk}" checked>')
        self.assertContains(page, 'data-subscription-provider="cloudpayments"')
        self.assertContains(page, 'data-provider-action="/payments/checkout/paid_subscription/"')
        self.assertContains(page, f'name="analyst_id" value="{self.analyst.pk}"')
        self.assertNotContains(page, 'value="balance"')
        self.assertNotContains(page, "Реальный баланс")
        self.assertNotContains(page, "<html")
        self.assertIn("no-store", page.headers["Cache-Control"])

    def test_old_subscription_link_opens_modal_on_next_page(self):
        AnalystPaidPlan.objects.create(analyst=self.analyst, title="Месяц", duration_days=30, price=Decimal("990.00"))
        self.client.force_login(self.user)
        page = self.client.get(
            reverse("cabinet:paid_predictions_subscribe", args=[self.analyst.pk]),
            {"next": "/predictions/?prediction_type=paid"},
        )
        self.assertRedirects(page, f"/predictions/?prediction_type=paid&paid_subscribe={self.analyst.pk}", fetch_redirect_response=False)

    def test_subscription_next_url_cannot_redirect_offsite(self):
        AnalystPaidPlan.objects.create(analyst=self.analyst, title="Месяц", duration_days=30, price=Decimal("990.00"))
        self.client.force_login(self.user)
        page = self.client.get(
            reverse("cabinet:paid_predictions_subscribe", args=[self.analyst.pk]),
            {"next": "https://example.com/pay"},
        )
        self.assertRedirects(page, reverse("front:expert_profile", kwargs={"username": self.analyst.username}) + f"?paid_subscribe={self.analyst.pk}", fetch_redirect_response=False)

    def test_subscription_reader_cannot_force_balance_post(self):
        from cabinet.models import AnalystPaidSubscription
        from wallets.services import ensure_real_balance
        plan = AnalystPaidPlan.objects.create(analyst=self.analyst, title="Месяц", duration_days=30, price=Decimal("990.00"))
        wallet = ensure_real_balance(self.user)
        wallet.balance = Decimal("5000")
        wallet.save(update_fields=["balance"])
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("cabinet:paid_predictions_subscribe", args=[self.analyst.pk]),
            {"plan_id": plan.pk}, HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(AnalystPaidSubscription.objects.filter(subscriber=self.user).exists())
        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, Decimal("5000"))

    def test_capper_can_buy_subscription_with_balance(self):
        from cabinet.models import AnalystPaidSubscription
        from wallets.services import ensure_real_balance
        buyer = User.objects.create_user(username="balance-capper", role=User.Role.ANALYST)
        plan = AnalystPaidPlan.objects.create(analyst=self.analyst, title="Месяц", duration_days=30, price=Decimal("990.00"))
        wallet = ensure_real_balance(buyer)
        wallet.balance = Decimal("1500")
        wallet.save(update_fields=["balance"])
        self.client.force_login(buyer)
        url = reverse("cabinet:paid_predictions_subscribe", args=[self.analyst.pk])
        fragment = self.client.get(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertContains(fragment, 'value="balance"')
        self.assertContains(fragment, 'data-subscription-provider="cloudpayments"')
        response = self.client.post(url, {"plan_id": plan.pk, "next": "/predictions/"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"ok": True, "return_url": "/predictions/"})
        self.assertTrue(AnalystPaidSubscription.objects.filter(subscriber=buyer, analyst=self.analyst).exists())
        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, Decimal("510.00"))

    def test_subscription_balance_error_stays_in_modal(self):
        plan = AnalystPaidPlan.objects.create(analyst=self.analyst, title="Месяц", duration_days=30, price=Decimal("990.00"))
        buyer = User.objects.create_user(username="empty-balance-capper", role=User.Role.ANALYST)
        self.client.force_login(buyer)
        response = self.client.post(
            reverse("cabinet:paid_predictions_subscribe", args=[self.analyst.pk]),
            {"plan_id": plan.pk}, HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])
        self.assertTrue(response.json()["message"])

    def test_legacy_monthly_subscription_is_available_in_modal(self):
        AnalystProfile.objects.filter(user=self.analyst).update(paid_predictions_price=Decimal("550"))
        self.client.force_login(self.user)
        page = self.client.get(
            reverse("cabinet:paid_predictions_subscribe", args=[self.analyst.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertContains(page, 'name="plan_id" value="" checked>')
        self.assertContains(page, '550 ₽')
        self.assertContains(page, 'data-subscription-provider="cloudpayments"')
        self.assertNotContains(page, 'value="balance"')

    def test_renewal_summary_starts_after_existing_access_and_uses_local_timezone(self):
        from cabinet.models import AnalystPaidSubscription
        from cabinet.paid_predictions import build_paid_checkout_context
        from django.utils.formats import date_format
        expires_at = timezone.now() + timedelta(days=10)
        AnalystPaidSubscription.objects.create(
            analyst=self.analyst, subscriber=self.user, price=Decimal("100"),
            starts_at=timezone.now() - timedelta(days=20), expires_at=expires_at,
        )
        plan = AnalystPaidPlan.objects.create(analyst=self.analyst, title="Месяц", duration_days=30, price=Decimal("2000"))
        context = build_paid_checkout_context(self.user, self.analyst.analyst_profile, [plan])
        expected = date_format(timezone.localtime(expires_at + timedelta(days=30)), "j E Y, H:i")
        self.assertEqual(context["subscription_default"]["expires_label"], expected)

    def test_subscription_provider_availability_is_per_plan_price(self):
        from cabinet.paid_predictions import build_paid_checkout_context
        short = AnalystPaidPlan.objects.create(analyst=self.analyst, title="День", duration_days=1, price=Decimal("100"))
        monthly = AnalystPaidPlan.objects.create(analyst=self.analyst, title="Месяц", duration_days=30, price=Decimal("2000"))
        with patch("payments.utils.build_payment_options", side_effect=lambda price, *_args, **_kwargs: [{"code": "cloudpayments", "label": "Оплатить картой"}] if price < 1000 else []):
            context = build_paid_checkout_context(self.user, self.analyst.analyst_profile, [short, monthly])
        self.assertEqual(context["subscription_choices"][0]["providers"], ["cloudpayments"])
        self.assertEqual(context["subscription_choices"][1]["providers"], [])
        self.assertEqual(context["subscription_default"]["id"], str(monthly.pk))
        self.assertFalse(context["can_use_subscription_balance"])

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
