from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cabinet.models import CapperMonthlyStat, User
from cabinet.presence import UserPresence
from game.models import PredictionCoupon


TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(STORAGES=TEST_STORAGES)
class CapperRankingAndBadgeTests(TestCase):
    def _analyst(self, username: str, *, verified: bool = False):
        user = User.objects.create_user(
            username=username,
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        profile = user.analyst_profile
        profile.is_public = True
        profile.is_verified = verified
        profile.save(update_fields=["is_public", "is_verified", "updated_at"])
        return user

    def test_recent_pending_activity_does_not_put_admin_first(self):
        admin = self._analyst("admin")
        proven = self._analyst("proven-expert")

        for _ in range(8):
            PredictionCoupon.objects.create(
                author=admin,
                published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
                state_status=PredictionCoupon.StateStatus.PENDING,
                total_stake=Decimal("100.00"),
                possible_payout=Decimal("180.00"),
                published_at=timezone.now(),
            )

        for _ in range(5):
            PredictionCoupon.objects.create(
                author=proven,
                published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
                state_status=PredictionCoupon.StateStatus.WIN,
                total_stake=Decimal("100.00"),
                possible_payout=Decimal("150.00"),
                published_at=timezone.now(),
                settled_at=timezone.now(),
            )

        response = self.client.get(reverse("front:cappers_stats"))

        self.assertEqual(response.status_code, 200)
        experts = response.context["experts"]
        self.assertEqual(experts[0]["username"], "proven-expert")
        self.assertEqual(experts[1]["username"], "admin")
        self.assertGreater(experts[0]["ranking_score"], Decimal("0"))

    def test_roi_uses_30_day_period_and_refund_stake(self):
        analyst = self._analyst("period-expert")
        now = timezone.now()

        PredictionCoupon.objects.create(
            author=analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=PredictionCoupon.StateStatus.WIN,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("1000.00"),
            published_at=now - timedelta(days=40),
            settled_at=now - timedelta(days=40),
        )
        PredictionCoupon.objects.create(
            author=analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=PredictionCoupon.StateStatus.WIN,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("200.00"),
            published_at=now,
            settled_at=now,
        )
        PredictionCoupon.objects.create(
            author=analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=PredictionCoupon.StateStatus.REFUND,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("100.00"),
            published_at=now,
            settled_at=now,
        )

        response = self.client.get(reverse("front:cappers_stats"))

        self.assertEqual(response.status_code, 200)
        expert = next(
            item for item in response.context["experts"] if item["username"] == analyst.username
        )
        self.assertEqual(expert["roi_period_days"], 30)
        self.assertEqual(expert["settled_in_roi_period"], 2)
        self.assertEqual(Decimal(expert["roi"]).quantize(Decimal("0.1")), Decimal("50.0"))

    def test_expert_profile_uses_catalog_verified_svg(self):
        analyst = self._analyst("verified-expert", verified=True)

        response = self.client.get(
            reverse("front:expert_profile", kwargs={"username": analyst.username})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="capper-verified-bg"')
        self.assertContains(response, 'class="capper-verified-check"')
        self.assertNotContains(response, '>✓</span>')

    def test_cappers_table_renders_presence_status(self):
        analyst = self._analyst("online-table-expert")
        analyst.analyst_profile.display_name = "Online Table Expert"
        analyst.analyst_profile.save(update_fields=["display_name", "updated_at"])
        UserPresence.objects.create(user=analyst, last_seen_at=timezone.now())
        CapperMonthlyStat.objects.create(
            analyst=analyst,
            month=date(2026, 9, 1),
            bets_count=3,
            wins_count=2,
            losses_count=1,
            total_stake=Decimal("300.00"),
            total_profit=Decimal("60.00"),
            flat_profit_percent=Decimal("20.00"),
            roi=Decimal("20.00"),
            avg_coefficient=Decimal("1.80"),
            hit_rate=Decimal("66.67"),
        )

        response = self.client.get(reverse("front:cappers_table"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Online Table Expert")
        self.assertContains(response, "cappers-ranking-presence is-online")
        self.assertContains(response, "В сети")
