from django.test import TestCase
from django.urls import reverse

from .models import AnalystProfile, User


class CabinetStage3Tests(TestCase):
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

    def test_reader_cannot_open_analyst_dashboard(self):
        user = User.objects.create_user(
            username="reader2",
            password="safe-test-password",
            role=User.Role.READER,
        )
        self.client.force_login(user)

        response = self.client.get(reverse("cabinet:analyst_dashboard"))

        self.assertEqual(response.status_code, 403)

    def test_analyst_cannot_open_reader_dashboard(self):
        user = User.objects.create_user(
            username="analyst2",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.client.force_login(user)

        response = self.client.get(reverse("cabinet:reader_dashboard"))

        self.assertEqual(response.status_code, 403)
