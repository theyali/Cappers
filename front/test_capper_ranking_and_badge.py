from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from cabinet.models import User
from game.models import PredictionCoupon


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

    def test_expert_profile_uses_catalog_verified_svg(self):
        analyst = self._analyst("verified-expert", verified=True)

        response = self.client.get(
            reverse("front:expert_profile", kwargs={"username": analyst.username})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="capper-verified-bg"')
        self.assertContains(response, 'class="capper-verified-check"')
        self.assertNotContains(response, '>✓</span>')
