from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from cabinet.models import User, UserVipSubscription, VipPlan
from cabinet.vip import activate_vip, extend_vip, get_active_vip
from wallets.models import CoinTransaction
from wallets.services import ensure_coin_wallet


class VipServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="vip-service-user",
            password="test-password",
        )
        self.plan = VipPlan.objects.create(
            title="VIP 30",
            duration_days=30,
            price_coins=100,
            is_active=True,
        )

    def test_activate_vip_starts_now_without_active_period(self):
        before = timezone.now()
        subscription = activate_vip(
            self.user,
            self.plan,
            UserVipSubscription.Source.ADMIN,
        )
        after = timezone.now()

        self.assertGreaterEqual(subscription.starts_at, before)
        self.assertLessEqual(subscription.starts_at, after)
        self.assertEqual(
            subscription.ends_at,
            subscription.starts_at + timedelta(days=30),
        )
        self.assertEqual(subscription.duration_days, 30)
        self.assertEqual(subscription.plan, self.plan)

    def test_activate_vip_appends_to_existing_vip_tail(self):
        now = timezone.now()
        current_end = now + timedelta(days=12)
        UserVipSubscription.objects.create(
            user=self.user,
            plan=self.plan,
            starts_at=now - timedelta(days=18),
            ends_at=current_end,
            duration_days=30,
            source=UserVipSubscription.Source.PURCHASE,
        )

        subscription = activate_vip(
            self.user,
            self.plan,
            UserVipSubscription.Source.ADMIN,
        )

        self.assertEqual(subscription.starts_at, current_end)
        self.assertEqual(subscription.ends_at, current_end + timedelta(days=30))

    def test_extend_vip_after_expiration_starts_from_now(self):
        now = timezone.now()
        UserVipSubscription.objects.create(
            user=self.user,
            starts_at=now - timedelta(days=20),
            ends_at=now - timedelta(days=10),
            duration_days=10,
            source=UserVipSubscription.Source.BONUS,
        )

        before = timezone.now()
        subscription = extend_vip(
            self.user,
            7,
            UserVipSubscription.Source.ROULETTE,
        )
        after = timezone.now()

        self.assertGreaterEqual(subscription.starts_at, before)
        self.assertLessEqual(subscription.starts_at, after)
        self.assertEqual(subscription.ends_at, subscription.starts_at + timedelta(days=7))
        self.assertEqual(subscription.source, UserVipSubscription.Source.ROULETTE)

    def test_get_active_vip_returns_current_period(self):
        now = timezone.now()
        current = UserVipSubscription.objects.create(
            user=self.user,
            plan=self.plan,
            starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(days=5),
            duration_days=6,
            source=UserVipSubscription.Source.PURCHASE,
        )

        self.assertEqual(get_active_vip(self.user, at=now), current)


class VipPurchaseTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="vip-purchase-user",
            password="test-password",
        )
        self.plan = VipPlan.objects.create(
            title="VIP 7",
            duration_days=7,
            price_coins=100,
            is_active=True,
        )
        wallet = ensure_coin_wallet(self.user)
        wallet.balance = 500
        wallet.save(update_fields=["balance", "updated_at"])
        self.client.force_login(self.user)

    def test_purchase_creates_subscription_and_charges_coins(self):
        response = self.client.post(
            reverse("cabinet:vip_purchase"),
            {"plan_id": self.plan.pk},
        )

        self.assertEqual(response.status_code, 200)
        subscription = UserVipSubscription.objects.get(
            user=self.user,
            source=UserVipSubscription.Source.PURCHASE,
        )
        self.assertEqual(subscription.plan, self.plan)
        self.assertEqual(subscription.duration_days, 7)

        self.user.coin_wallet.refresh_from_db()
        self.assertEqual(self.user.coin_wallet.balance, 400)
        self.assertTrue(
            CoinTransaction.objects.filter(
                user=self.user,
                kind=CoinTransaction.Kind.ADJUSTMENT,
                related_model="cabinet.uservipsubscription",
                related_id=subscription.pk,
                amount=-100,
            ).exists()
        )

    def test_purchase_extends_existing_vip(self):
        now = timezone.now()
        current_end = now + timedelta(days=5)
        UserVipSubscription.objects.create(
            user=self.user,
            plan=self.plan,
            starts_at=now - timedelta(days=2),
            ends_at=current_end,
            duration_days=7,
            source=UserVipSubscription.Source.PURCHASE,
        )

        response = self.client.post(
            reverse("cabinet:vip_purchase"),
            {"plan_id": self.plan.pk},
        )

        self.assertEqual(response.status_code, 200)
        latest = UserVipSubscription.objects.filter(user=self.user).order_by("-ends_at").first()
        self.assertEqual(latest.starts_at, current_end)
        self.assertEqual(latest.ends_at, current_end + timedelta(days=7))

    def test_failed_payment_rolls_back_new_vip_period(self):
        self.user.coin_wallet.balance = 10
        self.user.coin_wallet.save(update_fields=["balance", "updated_at"])

        response = self.client.post(
            reverse("cabinet:vip_purchase"),
            {"plan_id": self.plan.pk},
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            UserVipSubscription.objects.filter(
                user=self.user,
                source=UserVipSubscription.Source.PURCHASE,
            ).exists()
        )
        self.user.coin_wallet.refresh_from_db()
        self.assertEqual(self.user.coin_wallet.balance, 10)
