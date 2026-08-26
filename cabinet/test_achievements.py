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
            wins_count=10,
            overall_roi=Decimal("20.0"),
            followers_count=100,
            best_win_streak=5,
            is_verified=True,
        )

        self.assertEqual(
            [badge["key"] for badge in badges],
            ["wins-10", "roi-20", "followers-100", "streak-5", "verified"],
        )

    def test_badges_stay_hidden_below_thresholds(self):
        badges = build_achievement_badges(
            wins_count=9,
            overall_roi=Decimal("19.9"),
            followers_count=99,
            best_win_streak=4,
            is_verified=False,
        )

        self.assertEqual(badges, [])

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
                comment="Тест достижения",
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
            comment="Тест",
            state_status=Prediction.StateStatus.WIN,
        )

        response = self.client.get(
            reverse("cabinet:expert_profile", kwargs={"username": analyst.username})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-achievement="roi-20"')
        self.assertContains(response, 'data-achievement="verified"')
        self.assertNotContains(response, 'data-achievement="wins-10"')
