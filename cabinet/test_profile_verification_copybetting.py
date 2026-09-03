from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cabinet.models import User
from game.models import Match, PredictionCoupon
from wallets.models import CopiedBet, CopyBettingSubscription


TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(STORAGES=TEST_STORAGES)
class ProfileVerificationCopybettingTests(TestCase):
    def setUp(self):
        self.analyst = User.objects.create_user(
            username="copy-source",
            password="test-password",
            role=User.Role.ANALYST,
            email="copy-source@example.com",
            first_name="Copy",
            last_name="Source",
        )
        self.reader = User.objects.create_user(
            username="copy-reader",
            password="test-password",
            role=User.Role.READER,
        )

    def test_completed_analyst_can_request_verification(self):
        profile = self.analyst.analyst_profile
        profile.display_name = "Copy Source"
        profile.bio = "Подробно описываю стратегию и опыт."
        profile.avatar = "analysts/avatars/test.jpg"
        profile.save(update_fields=["display_name", "bio", "avatar", "updated_at"])
        self.client.force_login(self.analyst)

        response = self.client.post(reverse("cabinet:request_verification"))

        self.assertEqual(response.status_code, 302)
        profile.refresh_from_db()
        self.assertIsNotNone(profile.verification_requested_at)

    def test_incomplete_analyst_cannot_request_verification(self):
        self.client.force_login(self.analyst)

        response = self.client.post(reverse("cabinet:request_verification"))

        self.assertEqual(response.status_code, 302)
        self.analyst.analyst_profile.refresh_from_db()
        self.assertIsNone(self.analyst.analyst_profile.verification_requested_at)

    def test_analyst_profile_shows_copybetting_audience_stats(self):
        subscription = CopyBettingSubscription.objects.create(
            user=self.reader,
            analyst=self.analyst,
            status=CopyBettingSubscription.Status.ACTIVE,
            bank_amount=Decimal("1000.00"),
            stake_percent=Decimal("10.00"),
            total_profit=Decimal("125.00"),
        )
        match = Match.objects.create(
            external_id=9301,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now() + timedelta(days=1),
        )
        coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("225.00"),
            confidence=70,
            published_at=timezone.now(),
        )
        CopiedBet.objects.create(
            subscription=subscription,
            user=self.reader,
            analyst=self.analyst,
            source_coupon=coupon,
            state_status=CopiedBet.StateStatus.WIN,
            stake=Decimal("100.00"),
            possible_payout=Decimal("225.00"),
            profit=Decimal("125.00"),
            settled_at=timezone.now(),
        )
        self.client.force_login(self.analyst)

        response = self.client.get(f"{reverse('cabinet:profile')}?tab=copybetting")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["copybetting_audience_active_count"], 1)
        self.assertEqual(response.context["copybetting_audience_profit"], Decimal("125.00"))
        self.assertEqual(response.context["copybetting_audience_copied_bets_count"], 1)
        self.assertContains(response, "Кто копирует вас")
        self.assertContains(response, "@copy-reader")
        self.assertContains(response, "125 ₽")
