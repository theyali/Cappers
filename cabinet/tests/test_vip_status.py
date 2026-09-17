from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from cabinet.models import User, UserVipSubscription, VipPlan
from cabinet.vip import annotate_vip_status


class VipStatusTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="vip-status-user",
            password="test-password",
        )
        self.plan = VipPlan.objects.create(
            title="VIP 30",
            duration_days=30,
            price_coins=100,
        )

    def create_subscription(self, *, starts_at, ends_at, is_active=True):
        return UserVipSubscription.objects.create(
            user=self.user,
            plan=self.plan,
            starts_at=starts_at,
            ends_at=ends_at,
            duration_days=30,
            is_active=is_active,
        )

    def test_user_is_vip_for_active_subscription(self):
        now = timezone.now()
        self.create_subscription(
            starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(days=29),
        )

        self.assertTrue(self.user.is_vip)

    def test_user_is_not_vip_for_inactive_future_or_expired_subscription(self):
        now = timezone.now()
        self.create_subscription(
            starts_at=now - timedelta(days=30),
            ends_at=now - timedelta(seconds=1),
        )
        self.create_subscription(
            starts_at=now + timedelta(days=1),
            ends_at=now + timedelta(days=31),
        )
        self.create_subscription(
            starts_at=now - timedelta(days=1),
            ends_at=now + timedelta(days=29),
            is_active=False,
        )

        self.assertFalse(self.user.is_vip)

    def test_vip_annotations_prepare_status_and_dates(self):
        now = timezone.now()
        latest_start = now - timedelta(hours=2)
        furthest_end = now + timedelta(days=40)
        self.create_subscription(
            starts_at=now - timedelta(days=10),
            ends_at=furthest_end,
        )
        self.create_subscription(
            starts_at=latest_start,
            ends_at=now + timedelta(days=10),
        )

        annotated_user = annotate_vip_status(
            User.objects.filter(pk=self.user.pk),
            at=now,
        ).get()

        self.assertTrue(annotated_user.is_vip_active)
        self.assertEqual(annotated_user.vip_ends_at, furthest_end)
        self.assertEqual(annotated_user.vip_activated_at, latest_start)

        with self.assertNumQueries(0):
            self.assertTrue(annotated_user.is_vip)

    def test_unsaved_user_is_not_vip_without_query(self):
        user = User(username="unsaved-vip-user")

        with self.assertNumQueries(0):
            self.assertFalse(user.is_vip)
