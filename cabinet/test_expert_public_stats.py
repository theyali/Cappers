from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from game.models import Match, Prediction, PredictionCoupon

from .models import User


TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(STORAGES=TEST_STORAGES)
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
        self.assertContains(response, "Выигрыш")
        self.assertContains(response, "Проигрыш")
        self.assertContains(response, "Статус")
        self.assertContains(response, "2-1")
        self.assertContains(response, "0-3")
        self.assertContains(response, "82%")

    def test_public_profile_shows_confidence_calibration(self):
        analyst = User.objects.create_user(
            username="calibration-expert",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        now = timezone.now()

        for state in [
            PredictionCoupon.StateStatus.WIN,
            PredictionCoupon.StateStatus.WIN,
            PredictionCoupon.StateStatus.WIN,
            PredictionCoupon.StateStatus.LOSE,
            PredictionCoupon.StateStatus.LOSE,
        ]:
            PredictionCoupon.objects.create(
                author=analyst,
                published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
                state_status=state,
                total_stake=Decimal("100.00"),
                possible_payout=Decimal("180.00"),
                confidence=80,
                published_at=now,
                settled_at=now,
            )
        PredictionCoupon.objects.create(
            author=analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=PredictionCoupon.StateStatus.REFUND,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("100.00"),
            confidence=80,
            published_at=now,
            settled_at=now,
        )
        PredictionCoupon.objects.create(
            author=analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=PredictionCoupon.StateStatus.PENDING,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("200.00"),
            confidence=80,
            published_at=now,
        )
        PredictionCoupon.objects.create(
            author=analyst,
            published_status=PredictionCoupon.PublishedStatus.DRAFT,
            state_status=PredictionCoupon.StateStatus.WIN,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("200.00"),
            confidence=80,
            published_at=now,
            settled_at=now,
        )

        response = self.client.get(
            reverse("front:expert_profile", kwargs={"username": analyst.username})
        )

        calibration = response.context["confidence_calibration"]
        row = calibration["rows"][0]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(calibration["total"], 5)
        self.assertEqual(calibration["refunds"], 1)
        self.assertEqual(calibration["average_abs_error"], 20.0)
        self.assertEqual(calibration["average_delta_label"], "завышает на 20,0 п.п.")
        self.assertEqual(calibration["accuracy_tone"], "danger")
        self.assertEqual(calibration["accuracy_label"], "сильное завышение")
        self.assertEqual(row["label"], "80-89%")
        self.assertEqual(row["actual_rate"], 60.0)
        self.assertEqual(row["declared_rate"], 80.0)
        self.assertEqual(row["accuracy_tone"], "danger")
        self.assertEqual(row["sample_label"], "Малая выборка")
        self.assertTrue(row["is_reliable"])
        self.assertContains(response, "Калибровка уверенности")
        self.assertContains(response, "сильное завышение")
        self.assertContains(response, "is-danger")
        self.assertContains(response, "80-89%")
        self.assertContains(response, "60,0%")
