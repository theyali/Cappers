from datetime import datetime, time, timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from cabinet.models import User
from game.models import Match
from notifications.models import MatchWatch


class WatchedMatchListTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="match-list-reader")
        self.client.force_login(self.user)
        tz = timezone.get_current_timezone()
        base = timezone.make_aware(datetime.combine(timezone.localdate(), time(12, 0)), tz)
        self.regular = Match.objects.create(
            external_id=890001,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=base + timedelta(minutes=15),
        )
        self.watched = Match.objects.create(
            external_id=890002,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=base + timedelta(minutes=45),
        )
        MatchWatch.objects.create(
            user=self.user,
            match=self.watched,
            last_scope=Match.SyncScope.PREMATCH,
        )

    def test_watched_match_is_first_in_all_scope(self):
        response = self.client.get(reverse("game:match_list"))
        self.assertEqual(response.status_code, 200)
        matches = list(response.context["matches"])
        self.assertEqual(matches[0].id, self.watched.id)
        self.assertTrue(matches[0].is_watched)

    def test_watched_scope_contains_only_active_watches(self):
        response = self.client.get(reverse("game:match_list"), {"scope": "watched"})
        self.assertEqual(response.status_code, 200)
        matches = list(response.context["matches"])
        self.assertEqual([match.id for match in matches], [self.watched.id])
        watched_tab = next(tab for tab in response.context["scope_tabs"] if tab["scope"] == "watched")
        self.assertEqual(watched_tab["count"], 1)
