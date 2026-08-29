from datetime import date

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase

from .expert_profile_views import _recommended_experts
from .models import AnalystFollow, AnalystProfile, CapperMonthlyStat, User


class ExpertRecommendationsTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.current_user = User.objects.create_user(
            username="current-capper",
            password="test",
            role=User.Role.ANALYST,
        )
        self.current_profile = AnalystProfile.objects.create(
            user=self.current_user,
            display_name="Current Capper",
            is_public=True,
            is_recommended=True,
        )
        self.recommended_user = User.objects.create_user(
            username="recommended-capper",
            password="test",
            role=User.Role.ANALYST,
        )
        self.recommended_profile = AnalystProfile.objects.create(
            user=self.recommended_user,
            display_name="Recommended Capper",
            is_public=True,
            is_recommended=True,
        )
        self.hidden_user = User.objects.create_user(
            username="regular-capper",
            password="test",
            role=User.Role.ANALYST,
        )
        AnalystProfile.objects.create(
            user=self.hidden_user,
            display_name="Regular Capper",
            is_public=True,
            is_recommended=False,
        )
        CapperMonthlyStat.objects.create(
            analyst=self.recommended_user,
            month=date(2026, 8, 1),
            bets_count=12,
            wins_count=7,
            losses_count=4,
            refunds_count=1,
        )

    def test_only_flagged_other_experts_are_recommended(self):
        request = self.factory.get("/experts/current-capper/")
        request.user = AnonymousUser()

        recommendations = _recommended_experts(request, self.current_profile)

        self.assertEqual(len(recommendations), 1)
        self.assertEqual(recommendations[0]["username"], "recommended-capper")
        self.assertEqual(recommendations[0]["predictions_count"], 12)
        self.assertEqual(recommendations[0]["wins_count"], 7)
        self.assertEqual(recommendations[0]["losses_count"], 4)
        self.assertEqual(recommendations[0]["refunds_count"], 1)

    def test_follow_state_is_included_for_authenticated_viewer(self):
        viewer = User.objects.create_user(username="viewer", password="test")
        AnalystFollow.objects.create(follower=viewer, analyst=self.recommended_user)
        request = self.factory.get("/experts/current-capper/")
        request.user = viewer

        recommendations = _recommended_experts(request, self.current_profile)

        self.assertTrue(recommendations[0]["is_following"])
