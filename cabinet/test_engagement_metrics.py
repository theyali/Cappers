from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from front.models import PredictionFavorite, PredictionLike
from game.models import PredictionCoupon

from .dashboard_views import build_dashboard_context
from .models import AnalystProfile, User


class CapperEngagementMetricsTests(TestCase):
    def setUp(self):
        self.analyst = User.objects.create_user(
            username="engagement-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        profile, _ = AnalystProfile.objects.get_or_create(user=self.analyst)
        profile.display_name = "Engagement Capper"
        profile.is_public = True
        profile.save(update_fields=["display_name", "is_public"])

        self.reader_one = User.objects.create_user(
            username="engagement-reader-one",
            password="safe-test-password",
        )
        self.reader_two = User.objects.create_user(
            username="engagement-reader-two",
            password="safe-test-password",
        )

        self.published = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("10.00"),
            possible_payout=Decimal("20.00"),
            confidence=70,
        )
        self.draft = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.DRAFT,
            total_stake=Decimal("10.00"),
            possible_payout=Decimal("20.00"),
            confidence=60,
        )

        PredictionLike.objects.create(prediction=self.published, user=self.reader_one)
        PredictionLike.objects.create(prediction=self.published, user=self.reader_two)
        PredictionFavorite.objects.create(prediction=self.published, user=self.reader_one)

        # Draft reactions must never affect public/audience metrics.
        PredictionLike.objects.create(prediction=self.draft, user=self.reader_one)
        PredictionFavorite.objects.create(prediction=self.draft, user=self.reader_two)

    def test_dashboard_counts_only_published_prediction_engagement(self):
        context = build_dashboard_context(self.analyst)

        self.assertEqual(context["total_likes_count"], 2)
        self.assertEqual(context["total_saves_count"], 1)
        self.assertEqual(context["avg_likes_per_prediction"], 2.0)
        self.assertEqual(context["avg_saves_per_prediction"], 1.0)

    def test_public_profile_exposes_total_likes_and_saves(self):
        response = self.client.get(
            reverse("front:expert_profile", kwargs={"username": self.analyst.username})
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_likes_count"], 2)
        self.assertEqual(response.context["total_saves_count"], 1)
        html = response.content.decode("utf-8")
        self.assertIn("Лайки", html)
        self.assertIn("Сохранения", html)
