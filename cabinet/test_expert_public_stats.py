from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from game.models import Match, Prediction, PredictionCoupon

from .models import User


class ExpertPublicStatsTests(TestCase):
    def test_public_profile_calculates_roi_profit_and_market_stats(self):
        analyst = User.objects.create_user(
            username="stats-expert",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        now = timezone.now()

        win_match = Match.objects.create(
            external_id=910001,
            sync_scope=Match.SyncScope.FINISHED,
            score="2-1",
        )
        lose_match = Match.objects.create(
            external_id=910002,
            sync_scope=Match.SyncScope.FINISHED,
            score="0-3",
        )

        win_coupon = PredictionCoupon.objects.create(
            author=analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=PredictionCoupon.StateStatus.WIN,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("200.00"),
            confidence=82,
            published_at=now,
            settled_at=now,
        )
        lose_coupon = PredictionCoupon.objects.create(
            author=analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=PredictionCoupon.StateStatus.LOSE,
            total_stake=Decimal("50.00"),
            possible_payout=Decimal("90.00"),
            confidence=61,
            published_at=now,
            settled_at=now,
        )

        Prediction.objects.create(
            coupon=win_coupon,
            match=win_match,
            market="total",
            selection="ТБ 2.5",
            coefficient=Decimal("2.00"),
            stake=Decimal("100.00"),
            state_status=Prediction.StateStatus.WIN,
        )
        Prediction.objects.create(
            coupon=lose_coupon,
            match=lose_match,
            market="total",
            selection="ТМ 2.5",
            coefficient=Decimal("1.80"),
            stake=Decimal("50.00"),
            state_status=Prediction.StateStatus.LOSE,
        )

        response = self.client.get(
            reverse("front:expert_profile", kwargs={"username": analyst.username})
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["predictions_count"], 2)
        self.assertEqual(response.context["win_rate"], 50.0)
        self.assertEqual(response.context["total_profit"], Decimal("50.00"))
        self.assertEqual(response.context["settled_stake"], Decimal("150.00"))
        self.assertEqual(response.context["overall_roi"], 33.3)
        self.assertEqual(response.context["profit_periods"]["7"]["profit"], 50.0)
        self.assertEqual(response.context["profit_chart"]["7"][-1]["value"], 50.0)
        self.assertEqual(response.context["market_distribution"][0]["label"], "Тотал")
        self.assertEqual(response.context["market_distribution"][0]["win_rate"], 50)
        self.assertContains(response, "Динамика прибыли")
        self.assertContains(response, "Где эксперт сильнее")
        self.assertContains(response, "Выиграл")
        self.assertContains(response, "Проиграл")
        self.assertContains(response, "Счёт")
        self.assertContains(response, "2-1")
        self.assertContains(response, "0-3")
        self.assertContains(response, "82%")
