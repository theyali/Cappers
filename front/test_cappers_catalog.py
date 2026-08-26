from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from cabinet.models import User
from game.models import PredictionCoupon


class CappersCatalogTests(TestCase):
    def test_catalog_shows_roi_sidebar_favicon_and_achievements(self):
        analyst = User.objects.create_user(
            username="catalog-roi-expert",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        profile = analyst.analyst_profile
        profile.display_name = "ROI Expert"
        profile.save(update_fields=["display_name", "updated_at"])

        PredictionCoupon.objects.create(
            author=analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=PredictionCoupon.StateStatus.WIN,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("150.00"),
            published_at=timezone.now(),
            settled_at=timezone.now(),
        )

        response = self.client.get(reverse("front:cappers_stats"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ROI +50.0%")
        self.assertContains(response, 'class="bookmakers-sidebar"')
        self.assertContains(response, "/static/front/img/favicon.png")
        self.assertContains(response, 'class="capper-pro-achievements"')
        self.assertContains(response, "ROI +50%")
