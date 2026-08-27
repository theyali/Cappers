from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from cabinet.models import User
from game.models import Match

from .models import MatchWatch, Notification
from .tasks import _watched_match_update_events, notify_match_reminders


class MatchWatchLifecycleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="watch-reader")
        self.client.force_login(self.user)

    def test_live_watch_and_finished_rejection(self):
        live = Match.objects.create(external_id=880001, sync_scope=Match.SyncScope.LIVE, score="1:0")
        response = self.client.post(reverse("notifications:match_watch", args=[live.id]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["watching"])
        watch = MatchWatch.objects.get(user=self.user, match=live)
        self.assertEqual(watch.last_score, "1:0")
        self.assertIsNotNone(watch.started_sent_at)

        finished = Match.objects.create(external_id=880002, sync_scope=Match.SyncScope.FINISHED, score="2:1")
        response = self.client.post(reverse("notifications:match_watch", args=[finished.id]))
        self.assertEqual(response.status_code, 409)
        self.assertFalse(MatchWatch.objects.filter(user=self.user, match=finished).exists())

    def test_reminder_comes_from_match_watch(self):
        match = Match.objects.create(
            external_id=880003,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now() + timedelta(hours=1),
        )
        MatchWatch.objects.create(user=self.user, match=match, last_scope=Match.SyncScope.PREMATCH)
        created = notify_match_reminders()
        self.assertEqual(created, 1)
        self.assertTrue(Notification.objects.filter(event_key=f"match-reminder:{self.user.id}:{match.id}").exists())

    def test_start_score_halftime_and_final(self):
        match = Match.objects.create(external_id=880004, sync_scope=Match.SyncScope.PREMATCH)
        watch = MatchWatch.objects.create(user=self.user, match=match, last_scope=Match.SyncScope.PREMATCH)

        match.sync_scope = Match.SyncScope.LIVE
        match.score = "0:0"
        match.live_minute_label = "1"
        match.save()
        _watched_match_update_events()
        self.assertTrue(Notification.objects.filter(event_key=f"match-start:{self.user.id}:{match.id}").exists())

        match.score = "1:0"
        match.live_minute_label = "23"
        match.save()
        _watched_match_update_events()
        self.assertTrue(Notification.objects.filter(recipient=self.user, meta__match_id=match.id, meta__event="score").exists())

        match.time_status = "HT"
        match.live_minute_label = "HT"
        match.save()
        _watched_match_update_events()
        self.assertTrue(Notification.objects.filter(event_key=f"match-halftime:{self.user.id}:{match.id}").exists())

        match.sync_scope = Match.SyncScope.FINISHED
        match.score = "2:1"
        match.save()
        result = _watched_match_update_events()
        self.assertEqual(result["removed"], 1)
        self.assertTrue(Notification.objects.filter(event_key=f"match-final:{self.user.id}:{match.id}").exists())
        self.assertFalse(MatchWatch.objects.filter(pk=watch.pk).exists())
