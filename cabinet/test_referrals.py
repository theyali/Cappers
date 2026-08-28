from django.test import TestCase
from django.urls import reverse

from .models import AnalystFollow, AnalystProfile, CapperReferralVisit, User


class CapperReferralTests(TestCase):
    def setUp(self):
        self.capper = User.objects.create_user(
            username="refcapper",
            email="refcapper@example.com",
            password="test-pass-123",
            role=User.Role.ANALYST,
        )
        AnalystProfile.objects.create(
            user=self.capper,
            display_name="Referral Capper",
            is_public=True,
        )
        self.reader = User.objects.create_user(
            username="readerref",
            email="readerref@example.com",
            password="test-pass-123",
            role=User.Role.READER,
        )

    def test_referral_link_tracks_unique_session_and_total_clicks(self):
        url = reverse("front:capper_referral", kwargs={"username": self.capper.username})

        first = self.client.get(url)
        second = self.client.get(url)

        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        visits = CapperReferralVisit.objects.filter(analyst=self.capper)
        self.assertEqual(visits.count(), 1)
        self.assertEqual(visits.get().visits_count, 2)

    def test_follow_after_referral_is_counted_as_conversion(self):
        self.client.force_login(self.reader)
        referral_url = reverse("front:capper_referral", kwargs={"username": self.capper.username})
        self.client.get(referral_url)

        response = self.client.post(reverse("cabinet:toggle_follow", args=[self.capper.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(AnalystFollow.objects.filter(follower=self.reader, analyst=self.capper).exists())
        visit = CapperReferralVisit.objects.get(analyst=self.capper)
        self.assertEqual(visit.visitor, self.reader)
        self.assertIsNotNone(visit.subscribed_at)

    def test_referral_stats_show_visitors_clicks_and_subscriptions(self):
        self.client.force_login(self.reader)
        referral_url = reverse("front:capper_referral", kwargs={"username": self.capper.username})
        self.client.get(referral_url)
        self.client.get(referral_url)
        self.client.post(reverse("cabinet:toggle_follow", args=[self.capper.pk]))

        self.client.force_login(self.capper)
        response = self.client.get(reverse("cabinet:referral_stats"))
        payload = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["visitors_count"], 1)
        self.assertEqual(payload["clicks_count"], 2)
        self.assertEqual(payload["subscriptions_count"], 1)
        self.assertEqual(payload["conversion"], 100.0)
        self.assertIn(f"/r/{self.capper.username}/", payload["referral_url"])

    def test_reader_cannot_open_referral_stats(self):
        self.client.force_login(self.reader)
        response = self.client.get(reverse("cabinet:referral_stats"))
        self.assertEqual(response.status_code, 403)
