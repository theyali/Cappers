from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from cabinet.models import AnalystFollow, User
from game.models import PredictionCoupon


class CappersCatalogTests(TestCase):
    def _create_analyst(self, username="catalog-roi-expert"):
        analyst = User.objects.create_user(
            username=username,
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
        return analyst

    def test_catalog_shows_roi_sidebar_favicon_and_achievements(self):
        self._create_analyst()

        response = self.client.get(reverse("front:cappers_stats"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ROI +50.0%")
        self.assertContains(response, 'class="bookmakers-sidebar"')
        self.assertContains(response, "/static/front/img/favicon.png")
        self.assertContains(response, 'class="capper-pro-achievements"')
        self.assertContains(response, "ROI +50%")

    def test_guest_sees_follow_button_linking_to_login(self):
        self._create_analyst()

        response = self.client.get(reverse("front:cappers_stats"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="capper-pro-follow"')
        self.assertContains(response, "Подписаться")
        self.assertContains(response, reverse("cabinet:login"))

    def test_authenticated_user_sees_current_follow_state(self):
        analyst = self._create_analyst()
        reader = User.objects.create_user(
            username="catalog-reader",
            password="safe-test-password",
        )
        AnalystFollow.objects.create(follower=reader, analyst=analyst)
        self.client.force_login(reader)

        response = self.client.get(reverse("front:cappers_stats"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-expert-follow")
        self.assertContains(response, "Вы подписаны")
        self.assertContains(
            response,
            reverse("cabinet:toggle_follow", kwargs={"user_id": analyst.id}),
        )
        self.assertContains(response, "front/js/expert-follow.js")
