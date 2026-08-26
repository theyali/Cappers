from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from front.models import PredictionFavorite, PredictionLike
from game.models import Match, Prediction, PredictionCoupon

from .models import AnalystFollow, User


class CapperDashboardTests(TestCase):
    def setUp(self):
        self.analyst = User.objects.create_user(
            username="dashboard-analyst",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.reader = User.objects.create_user(
            username="dashboard-reader",
            password="safe-test-password",
            role=User.Role.READER,
        )
        self.now = timezone.now()

    def _match(self, external_id: int, *, scope=Match.SyncScope.LIVE, score="1-1"):
        return Match.objects.create(
            external_id=external_id,
            sync_scope=scope,
            starts_at=self.now,
            score=score,
        )

    def _coupon(self, *, state, stake, payout, settled=True):
        return PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=state,
            total_stake=Decimal(stake),
            possible_payout=Decimal(payout),
            settled_at=self.now if settled else None,
            published_at=self.now,
        )

    def test_reader_is_redirected_to_profile(self):
        self.client.force_login(self.reader)
        response = self.client.get(reverse("cabinet:dashboard"))
        self.assertRedirects(response, reverse("cabinet:profile"))

    def test_dashboard_shows_today_stats_roi_followers_reactions_and_live(self):
        win_coupon = self._coupon(
            state=PredictionCoupon.StateStatus.WIN,
            stake="100",
            payout="180",
        )
        lose_coupon = self._coupon(
            state=PredictionCoupon.StateStatus.LOSE,
            stake="50",
            payout="90",
        )
        pending_coupon = self._coupon(
            state=PredictionCoupon.StateStatus.PENDING,
            stake="40",
            payout="72",
            settled=False,
        )

        win_prediction = Prediction.objects.create(
            coupon=win_coupon,
            match=self._match(91001),
            market="total",
            selection="ТБ 2.5",
            coefficient=Decimal("1.80"),
            stake=Decimal("100"),
            confidence=80,
            state_status=Prediction.StateStatus.WIN,
        )
        Prediction.objects.create(
            coupon=lose_coupon,
            match=self._match(91002),
            market="winner",
            selection="Ничья",
            coefficient=Decimal("1.90"),
            stake=Decimal("50"),
            confidence=65,
            state_status=Prediction.StateStatus.LOSE,
        )
        Prediction.objects.create(
            coupon=pending_coupon,
            match=self._match(91003),
            market="both_score",
            selection="Обе забьют: да",
            coefficient=Decimal("1.70"),
            stake=Decimal("40"),
            confidence=74,
            state_status="",
        )

        AnalystFollow.objects.create(follower=self.reader, analyst=self.analyst)
        PredictionLike.objects.create(user=self.reader, prediction=win_prediction)
        PredictionFavorite.objects.create(user=self.reader, prediction=win_prediction)

        self.client.force_login(self.analyst)
        response = self.client.get(reverse("cabinet:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["today_stats"]["active"], 3)
        self.assertEqual(response.context["today_stats"]["wins"], 1)
        self.assertEqual(response.context["today_stats"]["losses"], 1)
        self.assertEqual(response.context["today_stats"]["pending"], 1)
        self.assertEqual(response.context["today_stats"]["live"], 3)
        self.assertEqual(response.context["new_followers_count"], 1)
        self.assertEqual(len(response.context["latest_reactions"]), 2)
        self.assertEqual(len(response.context["live_predictions"]), 3)
        self.assertEqual(response.context["roi_today_display"], "+20.0%")
        self.assertContains(response, "Текущие live-прогнозы")
        self.assertContains(response, "Последние реакции")
