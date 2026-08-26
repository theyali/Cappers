from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from game.models import Match, Prediction, PredictionCoupon

from .models import User
from .templatetags.achievement_tags import _best_win_streak, build_achievement_badges


class ExpertAchievementTests(TestCase):
    def test_all_badges_unlock_at_their_thresholds(self):
        badges = build_achievement_badges(
            predictions_count=50,
            wins_count=50,
            overall_roi=Decimal("50.0"),
            followers_count=250,
            best_win_streak=10,
            is_verified=True,
        )

        self.assertEqual(
            [badge["key"] for badge in badges],
            [
                "first-pick",
                "predictions-5",
                "predictions-25",
                "predictions-50",
                "wins-3",
                "wins-10",
                "wins-25",
                "wins-50",
                "roi-5",
                "roi-10",
                "roi-20",
                "roi-50",
                "followers-10",
                "followers-50",
                "followers-100",
                "followers-250",
                "streak-3",
                "streak-5",
                "streak-10",
                "verified",
            ],
        )

    def test_badges_stay_hidden_below_first_thresholds(self):
        badges = build_achievement_badges(
            predictions_count=0,
            wins_count=0,
            overall_roi=Decimal("0"),
            followers_count=0,
            best_win_streak=0,
            is_verified=False,
        )

        self.assertEqual(badges, [])

    def test_intermediate_badges_unlock_independently(self):
        badges = build_achievement_badges(
            predictions_count=5,
            wins_count=3,
            overall_roi=Decimal("10.0"),
            followers_count=10,
            best_win_streak=3,
            is_verified=False,
        )
        keys = [badge["key"] for badge in badges]

        self.assertIn("first-pick", keys)
        self.assertIn("predictions-5", keys)
        self.assertIn("wins-3", keys)
        self.assertIn("roi-5", keys)
        self.assertIn("roi-10", keys)
        self.assertIn("followers-10", keys)
        self.assertIn("streak-3", keys)
        self.assertNotIn("wins-10", keys)
        self.assertNotIn("roi-20", keys)

    def test_best_streak_uses_historical_winning_run(self):
        analyst = User.objects.create_user(
            username="streak-badge-expert",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        states = [
            Prediction.StateStatus.WIN,
            Prediction.StateStatus.WIN,
            Prediction.StateStatus.WIN,
            Prediction.StateStatus.WIN,
            Prediction.StateStatus.WIN,
            Prediction.StateStatus.LOSE,
        ]

        for index, state in enumerate(states, start=1):
            match = Match.objects.create(
                external_id=970000 + index,
                sync_scope=Match.SyncScope.FINISHED,
                score="2-1",
            )
            coupon = PredictionCoupon.objects.create(
                author=analyst,
                published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
                state_status=(
                    PredictionCoupon.StateStatus.WIN
                    if state == Prediction.StateStatus.WIN
                    else PredictionCoupon.StateStatus.LOSE
                ),
                total_stake=Decimal("100.00"),
                possible_payout=Decimal("200.00"),
                published_at=timezone.now(),
                settled_at=timezone.now(),
            )
            Prediction.objects.create(
                coupon=coupon,
                match=match,
                market="total",
                selection="ТБ 2.5",
                coefficient=Decimal("2.00"),
                stake=Decimal("100.00"),
                confidence=70,
                state_status=state,
            )

        self.assertEqual(_best_win_streak(analyst), 5)

    def test_public_profile_renders_unlocked_badges(self):
        analyst = User.objects.create_user(
            username="badge-public-expert",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        profile = analyst.analyst_profile
        profile.is_verified = True
        profile.save(update_fields=["is_verified", "updated_at"])

        match = Match.objects.create(
            external_id=971000,
            sync_scope=Match.SyncScope.FINISHED,
            score="3-1",
        )
        coupon = PredictionCoupon.objects.create(
            author=analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=PredictionCoupon.StateStatus.WIN,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("130.00"),
            published_at=timezone.now(),
            settled_at=timezone.now(),
        )
        Prediction.objects.create(
            coupon=coupon,
            match=match,
            market="total",
            selection="ТБ 2.5",
            coefficient=Decimal("1.30"),
            stake=Decimal("100.00"),
            confidence=75,
            state_status=Prediction.StateStatus.WIN,
        )

        response = self.client.get(
            reverse("cabinet:expert_profile", kwargs={"username": analyst.username})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-achievement="first-pick"')
        self.assertContains(response, 'data-achievement="roi-20"')
        self.assertContains(response, 'data-achievement="verified"')
        self.assertNotContains(response, 'data-achievement="wins-10"')
