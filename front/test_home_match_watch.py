from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from cabinet.models import User
from game.models import Match
from notifications.models import MatchWatch


class HomeMatchWatchTests(TestCase):
    def setUp(self):
        self.match = Match.objects.create(
            external_id=880001,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now() + timedelta(hours=3),
        )

    def test_reader_sees_active_bookmark_on_watched_home_match(self):
        reader = User.objects.create_user(
            username="home-reader",
            password="safe-test-password",
            role=User.Role.READER,
        )
        MatchWatch.objects.create(user=reader, match=self.match)
        self.client.force_login(reader)

        response = self.client.get(reverse("front:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-match-watch-toggle")
        self.assertContains(response, "match-card-watch-button is-watching")
        self.assertContains(
            response,
            reverse("notifications:match_watch", kwargs={"match_id": self.match.id}),
        )

    def test_analyst_home_card_uses_same_bookmark_control(self):
        analyst = User.objects.create_user(
            username="home-analyst",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        MatchWatch.objects.create(user=analyst, match=self.match)
        self.client.force_login(analyst)

        response = self.client.get(reverse("front:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-match-watch-toggle")
        self.assertContains(response, "match-card-watch-button is-watching")
