from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from game.models import Match

from .models import MatchPredictionRequest, User


class MatchPredictionDemandTests(TestCase):
    def setUp(self):
        self.reader = User.objects.create_user(
            username="demand-reader",
            password="safe-test-password",
            role=User.Role.READER,
        )
        self.capper = User.objects.create_user(
            username="demand-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.other = User.objects.create_user(
            username="demand-other",
            password="safe-test-password",
            role=User.Role.READER,
        )
        now = timezone.now()
        self.first_match = Match.objects.create(
            external_id=991001,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=now + timedelta(hours=2),
        )
        self.second_match = Match.objects.create(
            external_id=991002,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=now + timedelta(hours=1),
        )
        self.finished_match = Match.objects.create(
            external_id=991003,
            sync_scope=Match.SyncScope.FINISHED,
            starts_at=now - timedelta(hours=2),
        )

    def test_reader_can_toggle_prediction_request(self):
        self.client.force_login(self.reader)
        url = reverse("game:toggle_prediction_request", args=[self.first_match.pk])

        added = self.client.post(url)
        self.assertEqual(added.status_code, 200)
        self.assertTrue(added.json()["active"])
        self.assertEqual(added.json()["requests_count"], 1)
        self.assertTrue(
            MatchPredictionRequest.objects.filter(
                user=self.reader,
                match=self.first_match,
            ).exists()
        )

        removed = self.client.post(url)
        self.assertEqual(removed.status_code, 200)
        self.assertFalse(removed.json()["active"])
        self.assertEqual(removed.json()["requests_count"], 0)

    def test_capper_can_request_prediction_too(self):
        self.client.force_login(self.capper)
        response = self.client.post(
            reverse("game:toggle_prediction_request", args=[self.first_match.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["active"])

    def test_finished_match_cannot_receive_request(self):
        self.client.force_login(self.reader)
        response = self.client.post(
            reverse("game:toggle_prediction_request", args=[self.finished_match.pk])
        )
        self.assertEqual(response.status_code, 409)
        self.assertFalse(
            MatchPredictionRequest.objects.filter(match=self.finished_match).exists()
        )

    def test_public_state_shows_count_but_not_active_for_guest(self):
        MatchPredictionRequest.objects.create(user=self.reader, match=self.first_match)
        response = self.client.get(
            reverse("game:prediction_request_state", args=[self.first_match.pk])
        )
        payload = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["available"])
        self.assertFalse(payload["authenticated"])
        self.assertFalse(payload["active"])
        self.assertEqual(payload["requests_count"], 1)

    def test_capper_demand_is_sorted_by_request_count(self):
        MatchPredictionRequest.objects.create(user=self.reader, match=self.first_match)
        MatchPredictionRequest.objects.create(user=self.reader, match=self.second_match)
        MatchPredictionRequest.objects.create(user=self.other, match=self.second_match)

        self.client.force_login(self.capper)
        response = self.client.get(reverse("cabinet:prediction_demand"))
        payload = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["matches_count"], 2)
        self.assertEqual(payload["total_requests"], 3)
        self.assertEqual(payload["items"][0]["id"], self.second_match.id)
        self.assertEqual(payload["items"][0]["requests_count"], 2)

    def test_capper_can_sort_demand_by_match_time(self):
        MatchPredictionRequest.objects.create(user=self.reader, match=self.first_match)
        MatchPredictionRequest.objects.create(user=self.other, match=self.first_match)
        MatchPredictionRequest.objects.create(user=self.reader, match=self.second_match)

        self.client.force_login(self.capper)
        response = self.client.get(reverse("cabinet:prediction_demand"), {"sort": "time"})
        payload = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["sort"], "time")
        self.assertEqual(payload["items"][0]["id"], self.second_match.id)

    def test_reader_cannot_open_capper_demand_feed(self):
        self.client.force_login(self.reader)
        response = self.client.get(reverse("cabinet:prediction_demand"))
        self.assertEqual(response.status_code, 403)
