from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from cabinet.models import User
from game.models import Match, Prediction, PredictionCoupon


class MatchPredictionDistributionTests(TestCase):
    def setUp(self):
        self.analyst = User.objects.create_user(
            username="analyst_distribution",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.match = Match.objects.create(
            external_id=990001,
            sync_scope=Match.SyncScope.PREMATCH,
        )

    def _publish_prediction(self, market: str, selection: str):
        coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("10.00"),
            possible_payout=Decimal("20.00"),
        )
        return Prediction.objects.create(
            coupon=coupon,
            match=self.match,
            market=market,
            selection=selection,
            coefficient=Decimal("2.00"),
            stake=Decimal("10.00"),
            confidence=72,
        )

    def test_endpoint_returns_percentage_distribution_for_all_published_predictions(self):
        for _ in range(2):
            self._publish_prediction("total", "ТМ 2.5")
            self._publish_prediction("winner", "Хозяева")

        response = self.client.get(
            reverse("game:match_predictions", kwargs={"slug": self.match.slug})
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["total"], 4)

        distribution = {
            (item["market"], item["selection"]): item
            for item in payload["distribution"]
        }
        self.assertEqual(distribution[("total", "ТМ 2.5")]["count"], 2)
        self.assertEqual(distribution[("total", "ТМ 2.5")]["percent"], 50.0)
        self.assertEqual(distribution[("winner", "Хозяева")]["count"], 2)
        self.assertEqual(distribution[("winner", "Хозяева")]["percent"], 50.0)
        self.assertIn('class="prediction-card prediction-card-rich match-prediction-card', payload["html"])
        self.assertIn("ROI 0.0%", payload["html"])
        self.assertIn("72%", payload["html"])
