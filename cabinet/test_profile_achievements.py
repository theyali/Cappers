from django.test import TestCase
from django.urls import reverse

from .models import User


class ProfileAchievementsTabTests(TestCase):
    def test_analyst_can_open_own_achievements_tab(self):
        analyst = User.objects.create_user(
            username="achievements-owner",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.client.force_login(analyst)

        response = self.client.get(f"{reverse('cabinet:profile')}?tab=achievements")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_tab"], "achievements")
        self.assertEqual(response.context["achievement_overview"]["total_count"], 20)
        self.assertContains(response, "Достижения")
        self.assertContains(response, "Первый прогноз")
        self.assertContains(response, 'data-profile-tab-panel="achievements"')

    def test_reader_cannot_open_capper_achievements_tab(self):
        reader = User.objects.create_user(
            username="achievements-reader",
            password="safe-test-password",
            role=User.Role.READER,
        )
        self.client.force_login(reader)

        response = self.client.get(f"{reverse('cabinet:profile')}?tab=achievements")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_tab"], "profile")
        self.assertIsNone(response.context["achievement_overview"])
        self.assertNotContains(response, 'data-profile-tab-panel="achievements"')
