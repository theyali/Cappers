from datetime import timedelta
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

    def test_catalog_summary_is_rendered_before_ranking_and_discovery(self):
        self._create_analyst()

        response = self.client.get(reverse("front:cappers_stats"))

        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        hero_index = html.index('class="cappers-hero cappers-hero-pro"')
        summary_index = html.index('class="cappers-summary"')
        ranking_index = html.index('class="cappers-pro-grid"')
        discovery_index = html.index('class="capper-discovery-intro"')

        self.assertLess(hero_index, summary_index)
        self.assertLess(summary_index, ranking_index)
        self.assertLess(ranking_index, discovery_index)
        self.assertLess(html.index("Рейтинг по результатам"), ranking_index)
        self.assertLess(html.index("Все эксперты"), ranking_index)

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

    def test_catalog_renders_roi_period_select_and_skeleton_grid(self):
        self._create_analyst()

        response = self.client.get(reverse("front:cappers_stats"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-cappers-roi-select")
        self.assertContains(response, "ROI за 7 дней")
        self.assertContains(response, "ROI за 30 дней")
        self.assertContains(response, "ROI за 90 дней")
        self.assertContains(response, "ROI за все время")
        self.assertContains(response, "data-cappers-roi-grid")
        self.assertContains(response, "data-skeleton-block")
        self.assertContains(response, "front/js/cappers-roi-filter.js")
        self.assertContains(response, "admin/js/vendor/jquery/jquery.min.js")

    def test_ajax_roi_period_returns_only_ranking_fragment(self):
        self._create_analyst()

        response = self.client.get(
            reverse("front:cappers_stats"),
            {"roi_period": "7"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["period"], "7")
        self.assertEqual(payload["label"], "ROI за 7 дней")
        self.assertIn('class="capper-pro-card', payload["html"])
        self.assertIn("ROI +50.0% · 7д", payload["html"])
        self.assertNotIn("cappers-summary", payload["html"])

    def test_all_time_ajax_roi_includes_old_settled_predictions(self):
        analyst = self._create_analyst()
        old_date = timezone.now() - timedelta(days=120)
        PredictionCoupon.objects.create(
            author=analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=PredictionCoupon.StateStatus.LOSE,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("0.00"),
            published_at=old_date,
            settled_at=old_date,
        )

        response = self.client.get(
            reverse("front:cappers_stats"),
            {"roi_period": "all"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["period"], "all")
        self.assertEqual(payload["label"], "ROI за все время")
        self.assertIn("ROI -25.0% · всё время", payload["html"])
