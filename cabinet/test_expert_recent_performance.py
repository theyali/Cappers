from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from cabinet.expert_profile_views import _recent_performance
from cabinet.models import AnalystProfile, User
from game.models import PredictionCoupon


class ExpertRecentPerformanceTests(TestCase):
    def setUp(self):
        self.analyst = User.objects.create_user(
            username="performance_expert",
            password="test-password",
            role=User.Role.ANALYST,
        )
        self.profile = AnalystProfile.objects.create(
            user=self.analyst,
            display_name="Performance Expert",
            is_public=True,
        )

    def _coupon(self, state, days_ago):
        settled_at = timezone.now() - timedelta(days=days_ago)
        return PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=state,
            total_stake=100,
            possible_payout=200,
            published_at=settled_at - timedelta(hours=1),
            settled_at=settled_at,
        )

    def test_recent_window_uses_latest_settled_predictions(self):
        self._coupon(PredictionCoupon.StateStatus.LOSE, 12)
        self._coupon(PredictionCoupon.StateStatus.LOSE, 11)
        for day in range(10, 5, -1):
            self._coupon(PredictionCoupon.StateStatus.WIN, day)
        for day in range(5, 2, -1):
            self._coupon(PredictionCoupon.StateStatus.LOSE, day)
        self._coupon(PredictionCoupon.StateStatus.REFUND, 2)
        self._coupon(PredictionCoupon.StateStatus.REFUND, 1)

        performance = _recent_performance(self.analyst, 10)

        self.assertEqual(performance["total"], 10)
        self.assertEqual(performance["wins"], {"count": 5, "percent": 50})
        self.assertEqual(performance["losses"], {"count": 3, "percent": 30})
        self.assertEqual(performance["refunds"], {"count": 2, "percent": 20})

    def test_pending_predictions_do_not_affect_performance(self):
        self._coupon(PredictionCoupon.StateStatus.WIN, 2)
        PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=PredictionCoupon.StateStatus.PENDING,
            total_stake=100,
            possible_payout=180,
            published_at=timezone.now(),
        )

        performance = _recent_performance(self.analyst, 10)

        self.assertEqual(performance["total"], 1)
        self.assertEqual(performance["wins"]["percent"], 100)

    def test_public_profile_renders_performance_component(self):
        response = self.client.get(
            reverse("cabinet:expert_profile", kwargs={"username": self.analyst.username})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-expert-performance')
        self.assertContains(response, '10 прогнозов')
        self.assertContains(response, '100 прогнозов')
        self.assertContains(response, 'expert-recent-performance.css')
        self.assertContains(response, 'expert-recent-performance.js')
