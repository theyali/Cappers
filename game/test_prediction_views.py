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
            confidence=72,
        )
        return Prediction.objects.create(
            coupon=coupon,
            match=self.match,
            market=market,
            selection=selection,
            coefficient=Decimal("2.00"),
            stake=Decimal("10.00"),
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
        self.assertIn('class="content-table-row prediction-table-row"', payload["html"])
        self.assertIn("data-prediction-reaction", payload["html"])
        self.assertIn("prediction-like", payload["html"])
        self.assertIn("prediction-favorite", payload["html"])

    def test_endpoint_lazy_pages_cover_every_published_coupon_for_match(self):
        predictions = [
            self._publish_prediction("winner", f"Выбор {index}")
            for index in range(8)
        ]

        unrelated_match = Match.objects.create(
            external_id=990002,
            sync_scope=Match.SyncScope.PREMATCH,
        )
        unrelated_coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("10.00"),
            possible_payout=Decimal("20.00"),
            confidence=60,
        )
        Prediction.objects.create(
            coupon=unrelated_coupon,
            match=unrelated_match,
            market="winner",
            selection="Чужой матч",
            coefficient=Decimal("2.00"),
            stake=Decimal("10.00"),
        )

        draft_coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.DRAFT,
            total_stake=Decimal("10.00"),
            possible_payout=Decimal("20.00"),
            confidence=55,
        )
        Prediction.objects.create(
            coupon=draft_coupon,
            match=self.match,
            market="winner",
            selection="Черновик",
            coefficient=Decimal("2.00"),
            stake=Decimal("10.00"),
        )

        url = reverse("game:match_predictions", kwargs={"slug": self.match.slug})
        first = self.client.get(url, {"page": 1}).json()
        second = self.client.get(url, {"page": 2}).json()

        self.assertEqual(first["total"], 8)
        self.assertTrue(first["has_next"])
        self.assertEqual(first["next_page"], 2)
        self.assertFalse(second["has_next"])
        self.assertIsNone(second["next_page"])

        rendered = first["html"] + second["html"]
        for prediction in predictions:
            self.assertIn(
                f'data-prediction-card="{prediction.coupon_id}"',
                rendered,
            )
        self.assertNotIn(
            f'data-prediction-card="{unrelated_coupon.id}"',
            rendered,
        )
        self.assertNotIn(
            f'data-prediction-card="{draft_coupon.id}"',
            rendered,
        )
