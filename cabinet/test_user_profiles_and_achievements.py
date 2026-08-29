from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from front.models import PredictionFavorite, PredictionLike
from game.models import Match, PredictionCoupon
from notifications.models import MatchWatch

from .achievements import build_achievement_overview
from .forms import AnalystProfileForm
from .models import (
    AnalystFollow,
    AnalystProfile,
    CapperReferralVisit,
    MatchPredictionRequest,
    User,
)


class UserProfileAndAchievementTests(TestCase):
    def setUp(self):
        self.reader = User.objects.create_user(
            username="active-reader",
            email="private-reader@example.com",
            password="safe-test-password",
            role=User.Role.READER,
            first_name="Active",
            last_name="Reader",
        )
        self.capper = User.objects.create_user(
            username="activity-capper",
            email="capper@example.com",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.capper_profile, _ = AnalystProfile.objects.get_or_create(
            user=self.capper,
            defaults={
                "display_name": "Activity Capper",
                "specialization": "Футбол",
                "favorite_sports": "Футбол",
                "is_public": True,
            },
        )
        self.capper_profile.display_name = "Activity Capper"
        self.capper_profile.specialization = "Футбол"
        self.capper_profile.favorite_sports = "Футбол"
        self.capper_profile.is_public = True
        self.capper_profile.save()

        self.coupons = []
        for index in range(5):
            coupon = PredictionCoupon.objects.create(
                author=self.capper,
                published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
                total_stake=Decimal("100.00"),
                possible_payout=Decimal("150.00"),
                confidence=65,
                published_at=timezone.now(),
            )
            PredictionLike.objects.create(user=self.reader, prediction=coupon)
            PredictionFavorite.objects.create(user=self.reader, prediction=coupon)
            self.coupons.append(coupon)

        AnalystFollow.objects.create(follower=self.reader, analyst=self.capper)
        self.match = Match.objects.create(
            external_id=998001,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now(),
        )
        MatchWatch.objects.create(user=self.reader, match=self.match)
        MatchPredictionRequest.objects.create(user=self.reader, match=self.match)

    def test_reader_unlocks_like_and_favorite_achievements(self):
        overview = build_achievement_overview(self.reader)
        unlocked = {item["key"] for item in overview["items"] if item["unlocked"]}

        self.assertIn("likes-5", unlocked)
        self.assertIn("favorites-5", unlocked)
        self.assertNotIn("likes-10", unlocked)
        self.assertNotIn("favorites-10", unlocked)
        self.assertTrue(all(item["metric"] in {"likes_given", "favorites_saved"} for item in overview["items"]))

    def test_capper_unlocks_referral_achievement_at_five_conversions(self):
        now = timezone.now()
        for index in range(5):
            visitor = User.objects.create_user(
                username=f"ref-reader-{index}",
                password="safe-test-password",
                role=User.Role.READER,
            )
            CapperReferralVisit.objects.create(
                analyst=self.capper,
                visitor=visitor,
                session_key=f"ref-session-{index}",
                subscribed_at=now,
            )

        overview = build_achievement_overview(
            self.capper,
            followers_count=0,
            is_verified=False,
        )
        unlocked = {item["key"] for item in overview["items"] if item["unlocked"]}

        self.assertIn("referrals-5", unlocked)
        self.assertNotIn("referrals-10", unlocked)

    def test_telegram_profile_fields_are_optional(self):
        form = AnalystProfileForm(
            data={
                "display_name": "Activity Capper",
                "specialization": "Футбол",
                "bio": "",
                "favorite_sports": "Футбол",
                "favorite_leagues": "",
                "telegram_channel": "",
                "telegram_account": "",
                "instagram": "",
                "threads": "",
                "youtube": "",
                "tiktok": "",
                "facebook": "",
                "is_public": "on",
            },
            instance=self.capper_profile,
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_public_reader_profile_shows_activity_without_private_email(self):
        response = self.client.get(
            reverse("cabinet:user_profile", kwargs={"username": self.reader.username})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Active Reader")
        self.assertContains(response, "На платформе с")
        self.assertContains(response, "Матчи")
        self.assertContains(response, "Сохранено")
        self.assertContains(response, "Лайков")
        self.assertContains(response, "Подписки")
        self.assertContains(response, "Хочу прогноз")
        self.assertContains(response, 'data-achievement="likes-5"')
        self.assertContains(response, 'data-achievement="favorites-5"')
        self.assertNotContains(response, self.reader.email)

    def test_public_user_route_redirects_cappers_to_expert_profile(self):
        response = self.client.get(
            reverse("cabinet:user_profile", kwargs={"username": self.capper.username})
        )

        self.assertRedirects(
            response,
            reverse("front:expert_profile", kwargs={"username": self.capper.username}),
        )

    def test_following_summary_contains_profile_stats_and_clickable_url(self):
        self.client.force_login(self.reader)
        response = self.client.get(reverse("cabinet:following_summary"))
        payload = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["items"]), 1)
        item = payload["items"][0]
        self.assertEqual(item["username"], self.capper.username)
        self.assertEqual(item["display_name"], "Activity Capper")
        self.assertEqual(item["specialization"], "Футбол")
        self.assertEqual(item["predictions_count"], 5)
        self.assertEqual(
            item["url"],
            reverse("front:expert_profile", kwargs={"username": self.capper.username}),
        )

    def test_reader_achievement_endpoint_returns_only_activity_achievements(self):
        self.client.force_login(self.reader)
        response = self.client.get(reverse("cabinet:achievement_stats"))
        payload = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["is_analyst"])
        metrics = {item["metric"] for item in payload["items"]}
        self.assertEqual(metrics, {"likes_given", "favorites_saved"})
