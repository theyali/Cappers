from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import connections
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from back.models import WebsiteSettings
from cabinet.models import AnalystPaidSubscription, PaidPredictionPurchase, User
from cabinet.paid_prediction_purchases import buy_coupon_with_balance, refund_coupon_purchase
from cabinet.paid_predictions import user_can_view_paid_coupon
from game.models import Match, Prediction, PredictionCoupon
from notifications.models import Notification
from payments.models import Payment
from payments.services.checkout import single_coupon_order
from payments.services.fulfillment import fulfill_payment
from payments.services.processing import apply_provider_event
from payments.services.providers.base import ProviderEvent
from payments.utils import build_payment_status
from wallets.models import RealBalanceTransaction
from wallets.services import InsufficientBalance, ensure_real_balance, request_real_withdrawal, approve_real_withdrawal

STORAGES = {"default": {"BACKEND": "django.core.files.storage.FileSystemStorage"}, "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}


class PurchaseFixture:
    def setUp(self):
        self.author = User.objects.create_user(username="sale-author", role=User.Role.ANALYST)
        self.reader = User.objects.create_user(username="sale-reader")
        profile = self.author.analyst_profile
        profile.paid_predictions_enabled = profile.single_coupon_sales_enabled = True
        profile.single_coupon_price = Decimal("100")
        profile.save()
        self.match = Match.objects.create(external_id=7834331, sync_scope="prematch", starts_at=timezone.now() + timedelta(hours=1))
        self.coupon = PredictionCoupon.objects.create(author=self.author, total_stake=1, audience="paid", published_status="published", single_purchase_enabled=True, single_purchase_price=100)
        Prediction.objects.create(coupon=self.coupon, match=self.match, market="winner", selection="Секретный исход", coefficient=2, stake=1)
        balance = ensure_real_balance(self.reader)
        balance.balance = 500
        balance.save()

    def balances(self):
        return ensure_real_balance(self.reader).balance, ensure_real_balance(self.author).balance

    def payment(self):
        order = single_coupon_order(self.reader, self.coupon.pk)
        payment = Payment.objects.create(user=self.reader, provider="cloudpayments", amount=100, currency="RUB", status="succeeded", **order)
        payment.paid_at = timezone.now()
        payment.save(update_fields=["paid_at"])
        return payment


@override_settings(SINGLE_COUPON_SALES_ENABLED=True, STORAGES=STORAGES, CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}, CELERY_TASK_ALWAYS_EAGER=True)
class SingleCouponPaymentTests(PurchaseFixture, TestCase):
    def test_balance_purchase_is_atomic_idempotent_and_keeps_opens_zero(self):
        first = buy_coupon_with_balance(self.reader, self.coupon)
        second = buy_coupon_with_balance(self.reader, self.coupon)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(self.balances(), (Decimal("400"), Decimal("80")))
        self.assertEqual(RealBalanceTransaction.objects.filter(kind="coupon_purchase").count(), 1)
        self.assertEqual(RealBalanceTransaction.objects.filter(kind="coupon_income").count(), 1)
        self.assertEqual(Notification.objects.filter(kind="coupon_purchase").count(), 2)
        self.coupon.metrics.refresh_from_db()
        self.assertEqual(self.coupon.metrics.unique_opens_count, 0)
        self.assertTrue(user_can_view_paid_coupon(self.reader, self.coupon))

    def test_insufficient_balance_and_credit_failure_roll_back_everything(self):
        wallet = ensure_real_balance(self.reader)
        wallet.balance = 0
        wallet.save()
        with self.assertRaises(InsufficientBalance):
            buy_coupon_with_balance(self.reader, self.coupon)
        self.assertFalse(PaidPredictionPurchase.objects.exists())
        wallet.balance = 500
        wallet.save()
        with patch("wallets.services.credit_real_balance", side_effect=RuntimeError("write failed")):
            with self.assertRaises(RuntimeError):
                buy_coupon_with_balance(self.reader, self.coupon)
        self.assertFalse(PaidPredictionPurchase.objects.exists())
        self.assertEqual(self.balances(), (Decimal("500"), Decimal("0")))
        self.assertFalse(RealBalanceTransaction.objects.filter(kind="coupon_purchase").exists())

    def test_subscription_and_own_coupon_are_never_charged(self):
        AnalystPaidSubscription.objects.create(subscriber=self.reader, analyst=self.author, price=10, expires_at=timezone.now()+timedelta(days=1))
        self.assertIsNone(buy_coupon_with_balance(self.reader, self.coupon))
        self.assertIsNone(buy_coupon_with_balance(self.author, self.coupon))
        self.assertEqual(self.balances(), (Decimal("500"), Decimal("0")))

    def test_full_balance_refund_is_idempotent_and_repurchase_is_rejected(self):
        purchase = buy_coupon_with_balance(self.reader, self.coupon)
        refund_coupon_purchase(purchase)
        refund_coupon_purchase(purchase)
        self.assertEqual(self.balances(), (Decimal("500"), Decimal("0")))
        self.assertFalse(user_can_view_paid_coupon(self.reader, self.coupon))
        self.assertEqual(RealBalanceTransaction.objects.filter(kind="coupon_refund").count(), 1)
        with self.assertRaises(ValidationError):
            buy_coupon_with_balance(self.reader, self.coupon)

    def test_refund_of_held_income_removes_hold_without_debiting_available_balance(self):
        config = WebsiteSettings.load()
        config.single_coupon_income_hold_days = 3
        config.save()
        purchase = buy_coupon_with_balance(self.reader, self.coupon)
        self.assertEqual(ensure_real_balance(self.author).held, Decimal("80"))
        self.assertEqual(ensure_real_balance(self.author).balance, 0)
        refund_coupon_purchase(purchase)
        self.assertEqual(ensure_real_balance(self.author).held, 0)
        self.assertEqual(self.balances(), (Decimal("500"), Decimal("0")))

    def test_saved_fee_and_hold_survive_changes_in_settings(self):
        payment = self.payment()
        config = WebsiteSettings.load()
        config.single_coupon_fee_percent = 50
        config.single_coupon_income_hold_days = 9
        config.save()
        fulfill_payment(payment.pk)
        purchase = PaidPredictionPurchase.objects.get()
        self.assertEqual(purchase.platform_fee_percent, 20)
        self.assertEqual(purchase.capper_income, 80)
        self.assertEqual(ensure_real_balance(self.author).held, 0)

    def test_provider_fulfillment_repeated_and_late_delivery_does_not_charge_balance(self):
        payment = self.payment()
        self.match.starts_at = payment.paid_at + timedelta(seconds=1)
        self.match.sync_scope = "live"
        self.match.save()
        for _ in range(2):
            fulfill_payment(payment.pk)
        self.assertEqual(self.balances(), (Decimal("500"), Decimal("80")))
        self.assertEqual(RealBalanceTransaction.objects.filter(kind="coupon_income").count(), 1)
        self.assertTrue(user_can_view_paid_coupon(self.reader, self.coupon))

    def test_late_or_duplicate_external_money_requires_review_not_a_second_grant(self):
        payment = self.payment()
        Payment.objects.filter(pk=payment.pk).update(paid_at=self.match.starts_at)
        fulfilled = fulfill_payment(payment.pk)
        self.assertTrue(fulfilled.requires_review)
        self.assertIsNone(fulfilled.fulfilled_at)
        self.assertFalse(user_can_view_paid_coupon(self.reader, self.coupon))
        self.assertIn("проверке", build_payment_status(fulfilled)["title"])
        # Another order paid while the balance purchase won the race.
        timely = self.payment()
        buy_coupon_with_balance(self.reader, self.coupon)
        self.assertTrue(fulfill_payment(timely.pk).requires_review)
        self.assertEqual(self.balances(), (Decimal("400"), Decimal("80")))

    def test_provider_refund_reverses_access_and_income_once_without_balance_credit(self):
        payment = self.payment()
        fulfill_payment(payment.pk)
        event = ProviderEvent(event_type="refund", payment_public_id=str(payment.public_id), status="refunded", amount=Decimal("100"), currency="RUB", dedup_key="coupon-refund-1")
        apply_provider_event("cloudpayments", event)
        apply_provider_event("cloudpayments", event)
        self.assertFalse(user_can_view_paid_coupon(self.reader, self.coupon))
        self.assertEqual(self.balances(), (Decimal("500"), Decimal("0")))

    def test_refund_of_duplicate_provider_payment_does_not_revoke_balance_purchase(self):
        payment = self.payment()
        buy_coupon_with_balance(self.reader, self.coupon)
        fulfill_payment(payment.pk)
        apply_provider_event("cloudpayments", ProviderEvent(event_type="refund", payment_public_id=str(payment.public_id), status="refunded", amount=Decimal("100"), currency="RUB", dedup_key="extra-refund-1"))
        self.assertTrue(user_can_view_paid_coupon(self.reader, self.coupon))
        self.assertEqual(self.balances(), (Decimal("400"), Decimal("80")))

    def test_checkout_get_is_read_only_and_post_ignores_browser_price(self):
        self.reader.role = User.Role.ANALYST
        self.reader.save(update_fields=["role"])
        self.client.force_login(self.reader)
        url = reverse("cabinet:single_coupon_checkout", args=[self.coupon.pk])
        self.assertContains(self.client.get(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest"), "100")
        self.assertFalse(PaidPredictionPurchase.objects.exists())
        profile_response = self.client.get(reverse("front:expert_profile", args=[self.author.username]))
        self.assertFalse(profile_response.context["paid_predictions_enabled"])
        self.assertEqual(self.client.post(url, {"price": "1", "analyst_id": self.reader.pk}).status_code, 302)
        self.assertEqual(self.balances(), (Decimal("400"), Decimal("80")))
        self.assertContains(self.client.get(reverse("cabinet:coupon_purchases")), f"#{self.coupon.pk}")
        self.client.force_login(self.author)
        self.assertContains(self.client.get(reverse("cabinet:coupon_sales")), "Выручка")
        stranger = User.objects.create_user(username="no-sales-reader")
        self.client.force_login(stranger)
        self.assertNotContains(self.client.get(reverse("cabinet:coupon_purchases")), f"<td>#{self.coupon.pk}</td>", html=True)
        self.assertEqual(self.client.get(reverse("cabinet:coupon_sales")).status_code, 403)

    def test_coupon_checkout_link_returns_to_origin_and_opens_modal(self):
        self.client.force_login(self.reader)
        url = reverse("cabinet:single_coupon_checkout", args=[self.coupon.pk])
        response = self.client.get(url, {"next": "/predictions/?prediction_type=paid"})
        self.assertRedirects(response, f"/predictions/?prediction_type=paid&buy_coupon={self.coupon.pk}", fetch_redirect_response=False)
        response = self.client.get(url, {"next": "https://example.com/"})
        self.assertRedirects(response, reverse("front:prediction_detail", args=[self.coupon.pk]) + f"?buy_coupon={self.coupon.pk}", fetch_redirect_response=False)

    def test_reader_modal_shows_direct_payments_and_never_leaks_pick(self):
        self.client.force_login(self.reader)
        with patch("payments.utils.build_payment_options", return_value=[{"code": "cloudpayments", "label": "Оплатить картой"}]):
            response = self.client.get(reverse("cabinet:single_coupon_checkout", args=[self.coupon.pk]), HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertContains(response, "Покупка прогноза")
        self.assertContains(response, "Исход скрыт")
        self.assertContains(response, 'value="cloudpayments" checked')
        self.assertNotContains(response, 'value="balance"')
        self.assertNotContains(response, "Секретный исход")
        self.assertNotContains(response, "<html")
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertFalse(PaidPredictionPurchase.objects.exists())

    def test_reader_cannot_force_balance_payment_from_modal(self):
        self.client.force_login(self.reader)
        response = self.client.post(reverse("cabinet:single_coupon_checkout", args=[self.coupon.pk]), HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 403)
        self.assertFalse(response.json()["ok"])
        self.assertEqual(self.balances(), (Decimal("500"), Decimal("0")))

    def test_capper_modal_payment_returns_success_and_repeat_does_not_charge(self):
        self.reader.role = User.Role.ANALYST
        self.reader.save(update_fields=["role"])
        self.client.force_login(self.reader)
        url = reverse("cabinet:single_coupon_checkout", args=[self.coupon.pk])
        response = self.client.post(url, {"price": "1"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertIn("Прогноз открыт", response.json()["html"])
        self.assertIn("Открыть прогноз", response.json()["html"])
        response = self.client.post(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertTrue(response.json()["ok"])
        self.assertEqual(PaidPredictionPurchase.objects.count(), 1)
        self.assertEqual(self.balances(), (Decimal("400"), Decimal("80")))
        self.coupon.metrics.refresh_from_db()
        self.assertEqual(self.coupon.metrics.unique_opens_count, 0)
        self.assertContains(self.client.get(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest"), "Прогноз открыт")

    def test_started_match_disables_modal_payment_and_server_refuses_post(self):
        self.match.starts_at = timezone.now() - timedelta(seconds=1)
        self.match.save(update_fields=["starts_at"])
        self.reader.role = User.Role.ANALYST
        self.reader.save(update_fields=["role"])
        self.client.force_login(self.reader)
        url = reverse("cabinet:single_coupon_checkout", args=[self.coupon.pk])
        response = self.client.get(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertContains(response, "Матч начался, покупка недоступна.")
        self.assertNotContains(response, 'data-checkout-pay')
        response = self.client.post(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["message"], "Матч начался, покупка недоступна.")
        self.assertEqual(self.balances(), (Decimal("500"), Decimal("0")))

    def test_started_game_and_unknown_time_close_balance_and_provider_checkout(self):
        for value in (timezone.now(), None):
            self.match.starts_at = value
            self.match.save()
            with self.assertRaises(ValidationError):
                buy_coupon_with_balance(self.reader, self.coupon)
            with self.assertRaises(ValidationError):
                single_coupon_order(self.reader, self.coupon.pk)
        self.assertEqual(self.balances(), (Decimal("500"), Decimal("0")))

    def test_refund_after_withdrawal_records_author_debt_and_still_refunds_buyer(self):
        purchase = buy_coupon_with_balance(self.reader, self.coupon)
        config = WebsiteSettings.load()
        config.min_withdrawal_amount = 1
        config.save()
        request_real_withdrawal(self.author, 80, payout_details="Тестовые реквизиты")
        withdrawal = RealBalanceTransaction.objects.get(kind="withdrawal_request", user=self.author)
        approve_real_withdrawal(withdrawal, payout_reference="test-payout")
        refund_coupon_purchase(purchase)
        self.assertEqual(self.balances(), (Decimal("500"), Decimal("-80")))

    def test_withdrawals_are_limited_to_two_per_calendar_week(self):
        wallet = ensure_real_balance(self.author)
        wallet.balance = 3000
        wallet.save()
        for number in range(2):
            request_real_withdrawal(self.author, 500, payout_details="Тестовые реквизиты")
            withdrawal = RealBalanceTransaction.objects.filter(kind="withdrawal_request", user=self.author).latest("pk")
            approve_real_withdrawal(withdrawal, payout_reference=f"test-weekly-{number}")
        with self.assertRaises(ValidationError):
            request_real_withdrawal(self.author, 500, payout_details="Тестовые реквизиты")
        with patch("wallets.services.timezone.now", return_value=timezone.now()+timedelta(days=7)):
            request_real_withdrawal(self.author, 500, payout_details="Тестовые реквизиты")

    def test_configurable_price_bounds_apply_to_profile_and_sale(self):
        profile = self.author.analyst_profile
        profile.single_coupon_price = Decimal("49.99")
        with self.assertRaises(ValidationError):
            profile.full_clean()
        self.coupon.single_purchase_price = Decimal("49.99")
        self.coupon.save()
        with self.assertRaises(ValidationError):
            buy_coupon_with_balance(self.reader, self.coupon)

    def test_provider_checkout_uses_server_order_and_does_not_unlock_on_redirect(self):
        payment = self.payment()
        payment.checkout_url = "https://example.com/payment-test"
        self.client.force_login(self.reader)
        with patch("payments.views.start_checkout", return_value=payment) as start:
            response = self.client.post(reverse("payments:checkout", args=["single_coupon_purchase"]), {
                "coupon_id": self.coupon.pk, "provider": "cloudpayments", "price": "1", "analyst_id": self.reader.pk,
            })
        self.assertEqual(response.status_code, 302)
        order = start.call_args.args[1]
        self.assertEqual(order["amount_rub"], Decimal("100"))
        self.assertEqual(order["product_snapshot"]["analyst_id"], self.author.pk)
        self.assertFalse(user_can_view_paid_coupon(self.reader, self.coupon))


@override_settings(SINGLE_COUPON_SALES_ENABLED=True, STORAGES=STORAGES, CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}, CELERY_TASK_ALWAYS_EAGER=True)
class SingleCouponConcurrencyTests(PurchaseFixture, TransactionTestCase):
    def test_two_balance_requests_make_only_one_charge(self):
        barrier = Barrier(2)
        def buy():
            try:
                user = User.objects.get(pk=self.reader.pk)
                coupon = PredictionCoupon.objects.select_related("author").get(pk=self.coupon.pk)
                barrier.wait(timeout=10)
                return buy_coupon_with_balance(user, coupon).pk
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: buy(), range(2)))
        self.assertEqual(results[0], results[1])
        self.assertEqual(self.balances(), (Decimal("400"), Decimal("80")))

    def test_held_income_release_and_refund_can_race(self):
        from wallets.services import release_held_real_income
        config = WebsiteSettings.load()
        config.single_coupon_income_hold_days = 3
        config.save()
        purchase = buy_coupon_with_balance(self.reader, self.coupon)
        RealBalanceTransaction.objects.filter(kind="coupon_income").update(available_at=timezone.now()-timedelta(seconds=1))
        barrier = Barrier(2)
        def run(refund):
            try:
                barrier.wait(timeout=10)
                if refund:
                    refund_coupon_purchase(PaidPredictionPurchase.objects.select_related("buyer", "analyst").get(pk=purchase.pk))
                else:
                    release_held_real_income()
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(run, [True, False]))
        self.assertEqual(self.balances(), (Decimal("500"), Decimal("0")))
        self.assertEqual(ensure_real_balance(self.author).held, 0)

    def test_external_payment_and_balance_purchase_race_only_grants_once(self):
        payment = self.payment()
        barrier = Barrier(2)
        def run(external):
            try:
                barrier.wait(timeout=10)
                if external:
                    fulfill_payment(payment.pk)
                else:
                    buy_coupon_with_balance(User.objects.get(pk=self.reader.pk),
                        PredictionCoupon.objects.select_related("author").get(pk=self.coupon.pk))
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(run, [True, False]))
        buyer_balance, author_balance = self.balances()
        self.assertIn(buyer_balance, (Decimal("400"), Decimal("500")))
        self.assertEqual(author_balance, Decimal("80"))
        self.assertEqual(PaidPredictionPurchase.objects.filter(status="paid").count(), 1)
        self.assertEqual(RealBalanceTransaction.objects.filter(kind="coupon_income").count(), 1)
        payment.refresh_from_db()
        self.assertEqual(payment.requires_review, buyer_balance == Decimal("400"))

    def test_buying_can_race_with_a_withdrawal_on_the_same_wallet(self):
        from django.db import transaction
        from wallets.models import CapperRealBalance
        from cabinet import paid_prediction_purchases as service
        self.reader.role = User.Role.ANALYST
        self.reader.save()
        config = WebsiteSettings.load()
        config.min_withdrawal_amount = 1
        config.save()
        barrier = Barrier(2)
        lock_participants = service._lock_participants
        def lock_then_wait(buyer, analyst):
            lock_participants(buyer, analyst)
            barrier.wait(timeout=10)
        def run(withdraw):
            try:
                if withdraw:
                    with transaction.atomic():
                        CapperRealBalance.objects.select_for_update().get(user_id=self.reader.pk)
                        barrier.wait(timeout=10)
                        request_real_withdrawal(User.objects.get(pk=self.reader.pk), 100, payout_details="Тестовые реквизиты")
                else:
                    buy_coupon_with_balance(User.objects.get(pk=self.reader.pk),
                        PredictionCoupon.objects.select_related("author").get(pk=self.coupon.pk))
            finally:
                connections.close_all()
        with patch.object(service, "_lock_participants", side_effect=lock_then_wait):
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(run, [True, False]))
        self.assertEqual(self.balances(), (Decimal("300"), Decimal("80")))
        self.assertEqual(ensure_real_balance(self.reader).pending_withdrawal, 100)
