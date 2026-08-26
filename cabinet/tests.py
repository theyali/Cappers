from django.test import TestCase
from django.urls import reverse

from .models import AnalystFollow, AnalystProfile, User


class CabinetProfileTests(TestCase):
    def test_analyst_profile_is_created_for_analyst(self):
        user = User.objects.create_user(
            username="analyst",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.assertTrue(AnalystProfile.objects.filter(user=user).exists())

    def test_reader_does_not_get_analyst_profile(self):
        user = User.objects.create_user(
            username="reader",
            password="safe-test-password",
            role=User.Role.READER,
        )
        self.assertFalse(AnalystProfile.objects.filter(user=user).exists())

    def test_dashboard_redirects_to_profile(self):
        user = User.objects.create_user(
            username="reader2",
            password="safe-test-password",
            role=User.Role.READER,
        )
        self.client.force_login(user)
        response = self.client.get(reverse("cabinet:dashboard"))
        self.assertRedirects(response, reverse("cabinet:profile"))

    def test_legacy_dashboards_redirect_to_profile(self):
        user = User.objects.create_user(
            username="analyst2",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.client.force_login(user)

        for route_name in ("cabinet:analyst_dashboard", "cabinet:reader_dashboard"):
            response = self.client.get(reverse(route_name))
            self.assertRedirects(response, reverse("cabinet:profile"))

    def test_follow_counts_are_backed_by_database(self):
        analyst = User.objects.create_user(
            username="analyst3",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        follower = User.objects.create_user(
            username="reader3",
            password="safe-test-password",
            role=User.Role.READER,
        )
        AnalystFollow.objects.create(follower=follower, analyst=analyst)

        self.client.force_login(analyst)
        response = self.client.get(reverse("cabinet:profile"))

        self.assertEqual(response.context["followers_count"], 1)
        self.assertEqual(response.context["following_count"], 0)

    def test_reader_cannot_open_analyst_only_profile_tabs(self):
        reader = User.objects.create_user(
            username="reader-tabs",
            password="safe-test-password",
            role=User.Role.READER,
        )
        self.client.force_login(reader)

        for tab in ("predictions", "followers"):
            response = self.client.get(reverse("cabinet:profile"), {"tab": tab})
            self.assertEqual(response.context["active_tab"], "profile")
            self.assertNotContains(response, "profile-hero-shade")
            self.assertNotContains(response, "Мои прогнозы")
            self.assertNotContains(response, "Кто следит за вами")

    def test_analyst_keeps_predictions_followers_and_stats(self):
        analyst = User.objects.create_user(
            username="analyst-tabs",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.client.force_login(analyst)

        response = self.client.get(reverse("cabinet:profile"), {"tab": "followers"})

        self.assertEqual(response.context["active_tab"], "followers")
        self.assertContains(response, "profile-hero-shade")
        self.assertContains(response, "Мои прогнозы")
        self.assertContains(response, "Кто следит за вами")
