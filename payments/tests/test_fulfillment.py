from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from cabinet.models import (
    AnalystPaidSubscription,
    AnalystPaidSubscriptionPayment,
    AnalystProfile,
    User,
    UserVipSubscription,
    VipPlan,
)
from payments.models import Payment
from payments.services.fulfillment import fulfill_payment
from payments.tasks import expire_stale_payments, reconcile_pending_payments
from payments.tests.test_cloudpayments import CLOUDPAYMENTS_SETTINGS, api_answer, post_notification
from payments.tests.test_models import TEST_STORAGES, make_payment
from wallets.models import CoinPackage, CoinTransaction, RealBalanceTransaction
from wallets.services import ensure_real_balance


@override_settings(STORAGES=TEST_STORAGES, **CLOUDPAYMENTS_SETTINGS)
class FulfillmentTests(TestCase):
    def setUp(self):
        self.buyer = User.objects.create_user(username="pay-buyer", password="safe-test-password")
        self.analyst = User.objects.create_user(
            username="pay-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        AnalystProfile.objects.filter(user=self.analyst).update(paid_predictions_enabled=True)

    def paid(self, purpose, terms, *, user=None, price="499.00", **extra):
        values = {
            "purpose": purpose,
            "product_snapshot": terms,
            "amount": Decimal(price),
            "amount_rub": Decimal(price),
            "status": Payment.Status.SUCCEEDED,
            "paid_at": timezone.now(),
        }
        values.update(extra)
        return make_payment(user or self.buyer, **values)

    def subscription_terms(self, **extra):
        terms = {
            "analyst_id": self.analyst.pk,
            "plan_id": None,
            "plan_title": "30 дней",
            "duration_days": 30,
            "price_rub": "990.00",
            "platform_fee_percent": "20.00",
        }
        terms.update(extra)
        return terms

    def package_purchases(self, payment):
        return CoinTransaction.objects.filter(
            user=payment.user,
            kind=CoinTransaction.Kind.PACKAGE_PURCHASE,
            related_model="payments.payment",
            related_id=payment.pk,
        )

    def test_coin_package_is_delivered_by_its_snapshot_once(self):
        package = CoinPackage.objects.create(title="Старт", coins=1000, bonus_coins=100, price_rub=Decimal("499.00"))
        payment = self.paid(
            Payment.Purpose.COIN_PACKAGE,
            {"package_id": package.pk, "title": "Старт", "coins": 1000, "bonus_coins": 100, "price_rub": "499.00"},
            coin_package=package,
        )
        # Edited and withdrawn after the payment: the buyer still gets what was paid for.
        CoinPackage.objects.filter(pk=package.pk).update(coins=10, is_active=False)

        fulfill_payment(payment.pk)
        fulfill_payment(payment.pk)

        payment.refresh_from_db()
        self.assertIsNotNone(payment.fulfilled_at)
        self.assertEqual([t.amount for t in self.package_purchases(payment)], [1100])

    def test_paid_subscription_is_delivered_on_its_terms_without_a_balance_debit(self):
        first = self.paid(Payment.Purpose.PAID_SUBSCRIPTION, self.subscription_terms(), price="990.00")
        second = self.paid(Payment.Purpose.PAID_SUBSCRIPTION, self.subscription_terms(), price="990.00")

        fulfill_payment(first.pk)
        fulfill_payment(first.pk)
        subscription = AnalystPaidSubscription.objects.get(subscriber=self.buyer, analyst=self.analyst)
        first_end = subscription.expires_at
        fulfill_payment(second.pk)

        subscription.refresh_from_db()
        self.assertEqual(subscription.expires_at, first_end + timedelta(days=30))
        sales = AnalystPaidSubscriptionPayment.objects.filter(subscription=subscription).order_by("id")
        self.assertEqual([sale.payment_id for sale in sales], [first.pk, second.pk])
        # The platform fee fixed at checkout (20 %) applies, the income waits in the hold.
        self.assertEqual([sale.capper_income for sale in sales], [Decimal("792.00"), Decimal("792.00")])
        self.assertEqual(ensure_real_balance(self.analyst).held, Decimal("1584.00"))
        self.assertFalse(
            RealBalanceTransaction.objects.filter(
                user=self.buyer,
                kind=RealBalanceTransaction.Kind.PAID_PREDICTION_PURCHASE,
            ).exists()
        )

    def test_vip_follows_the_current_period_unless_a_switch_was_confirmed(self):
        monthly = VipPlan.objects.create(title="VIP 30", duration_days=30, price_rub=Decimal("300"))
        weekly = VipPlan.objects.create(title="VIP 7", duration_days=7, price_rub=Decimal("100"))
        now = timezone.now()
        current = UserVipSubscription.objects.create(
            user=self.analyst,
            plan=monthly,
            starts_at=now - timedelta(days=10),
            ends_at=now + timedelta(days=20),
            duration_days=30,
        )
        terms = {"plan_id": weekly.pk, "title": "VIP 7", "duration_days": 7, "price_rub": "100.00"}
        appended = self.paid(Payment.Purpose.VIP_PLAN, {**terms, "switch": False}, user=self.analyst, price="100.00")
        switched = self.paid(Payment.Purpose.VIP_PLAN, {**terms, "switch": True}, user=self.analyst, price="100.00")

        fulfill_payment(appended.pk)
        appended_period = UserVipSubscription.objects.get(payment=appended)
        self.assertEqual(appended_period.starts_at, current.ends_at)
        self.assertEqual(appended_period.duration_days, 7)

        fulfill_payment(switched.pk)
        switched_period = UserVipSubscription.objects.get(payment=switched)
        self.assertAlmostEqual(switched_period.starts_at, timezone.now(), delta=timedelta(minutes=1))
        self.assertEqual(
            list(UserVipSubscription.objects.filter(user=self.analyst, is_active=True)),
            [switched_period],
        )

    def test_unpaid_payment_is_not_delivered(self):
        payment = self.paid(Payment.Purpose.PAID_SUBSCRIPTION, self.subscription_terms(), status=Payment.Status.PENDING)

        fulfill_payment(payment.pk)

        payment.refresh_from_db()
        self.assertIsNone(payment.fulfilled_at)
        self.assertFalse(AnalystPaidSubscription.objects.exists())

    def test_pay_notification_delivers_after_the_commit(self):
        payment = self.paid(
            Payment.Purpose.COIN_PACKAGE,
            {"package_id": 1, "title": "Старт", "coins": 1000, "bonus_coins": 100, "price_rub": "499.00"},
            status=Payment.Status.PENDING,
            paid_at=None,
        )
        fields = {
            "TransactionId": "5001",
            "Amount": "499.00",
            "Currency": "RUB",
            "InvoiceId": str(payment.public_id),
            "AccountId": str(self.buyer.pk),
            "TestMode": "0",
            "Status": "Completed",
        }

        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(post_notification(self.client, "pay", fields).json(), {"code": 0})

        payment.refresh_from_db()
        self.assertIsNotNone(payment.fulfilled_at)
        self.assertEqual(self.package_purchases(payment).count(), 1)

    def test_check_refuses_a_product_that_is_no_longer_sold(self):
        payment = self.paid(
            Payment.Purpose.PAID_SUBSCRIPTION,
            self.subscription_terms(),
            price="990.00",
            status=Payment.Status.PENDING,
            paid_at=None,
        )
        fields = {
            "TransactionId": "6001",
            "Amount": "990.00",
            "Currency": "RUB",
            "InvoiceId": str(payment.public_id),
            "AccountId": str(self.buyer.pk),
            "TestMode": "0",
        }
        self.assertEqual(post_notification(self.client, "check", fields).json(), {"code": 0})

        AnalystProfile.objects.filter(user=self.analyst).update(paid_predictions_enabled=False)

        self.assertEqual(post_notification(self.client, "check", {**fields, "TransactionId": "6002"}).json(), {"code": 13})

    def test_reconciliation_applies_lost_payments_and_retries_delivery(self):
        old = timezone.now() - timedelta(minutes=20)
        terms = {"package_id": 1, "title": "Старт", "coins": 1000, "bonus_coins": 100, "price_rub": "499.00"}
        lost = self.paid(Payment.Purpose.COIN_PACKAGE, terms, status=Payment.Status.PENDING, paid_at=None)
        undelivered = self.paid(Payment.Purpose.COIN_PACKAGE, terms, paid_at=old)
        broken = self.paid(Payment.Purpose.COIN_PACKAGE, {"package_id": 1}, paid_at=old)
        fresh = self.paid(Payment.Purpose.COIN_PACKAGE, terms, status=Payment.Status.PENDING, paid_at=None)
        Payment.objects.filter(pk__in=[lost.pk, undelivered.pk, broken.pk]).update(created_at=old)
        found = {
            "Success": True,
            "Model": {
                "TransactionId": 7001,
                "InvoiceId": str(lost.public_id),
                "AccountId": str(self.buyer.pk),
                "Amount": 499.0,
                "Currency": "RUB",
                "Status": "Completed",
                "TestMode": False,
            },
        }

        with (
            patch("payments.services.providers.http.urlopen", return_value=api_answer(found)) as urlopen,
            self.captureOnCommitCallbacks(execute=True),
            self.assertLogs("payments", "ERROR"),
        ):
            result = reconcile_pending_payments()

        # Only the old open order is asked about; the broken one is logged and skipped.
        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(result, {"checked": 1, "delivered": 1})
        for payment in (lost, undelivered, broken, fresh):
            payment.refresh_from_db()
        self.assertEqual(lost.status, Payment.Status.SUCCEEDED)
        self.assertIsNotNone(lost.fulfilled_at)
        self.assertIsNotNone(undelivered.fulfilled_at)
        self.assertIsNone(broken.fulfilled_at)
        self.assertEqual(fresh.status, Payment.Status.PENDING)

    def test_unpaid_orders_expire_after_a_grace_period(self):
        now = timezone.now()
        stale = make_payment(self.buyer, status=Payment.Status.PENDING, expires_at=now - timedelta(hours=1))
        recent = make_payment(self.buyer, status=Payment.Status.PENDING, expires_at=now - timedelta(minutes=5))
        confirming = make_payment(self.buyer, status=Payment.Status.PROCESSING, expires_at=now - timedelta(hours=1))

        with self.assertLogs("payments", "INFO"):
            self.assertEqual(expire_stale_payments(), 1)

        for payment in (stale, recent, confirming):
            payment.refresh_from_db()
        self.assertEqual(
            [stale.status, recent.status, confirming.status],
            [Payment.Status.EXPIRED, Payment.Status.PENDING, Payment.Status.PROCESSING],
        )
