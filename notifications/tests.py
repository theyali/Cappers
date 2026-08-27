from django.test import TestCase
from django.urls import reverse

from cabinet.models import User
from game.models import Match

from .models import MatchWatch, Notification
from .services import create_notification, get_preferences


class NotificationServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="reader-notifications",
            email="reader@example.com",
            password="test-password-123",
        )

    def test_event_key_is_idempotent(self):
        first = create_notification(
            recipient=self.user,
            kind=Notification.Kind.MATCH_REMINDER,
            title="Скоро матч",
            event_key="test:event:1",
        )
        second = create_notification(
            recipient=self.user,
            kind=Notification.Kind.MATCH_REMINDER,
            title="Скоро матч",
            event_key="test:event:1",
        )

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Notification.objects.count(), 1)

    def test_disabled_category_does_not_create_notification(self):
        preferences = get_preferences(self.user)
        preferences.achievement = False
        preferences.save(update_fields=["achievement", "updated_at"])

        notification = create_notification(
            recipient=self.user,
            kind=Notification.Kind.ACHIEVEMENT,
            title="Достижение",
            event_key="test:achievement:1",
        )

        self.assertIsNone(notification)
        self.assertFalse(Notification.objects.exists())


class NotificationViewsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="reader-center",
            password="test-password-123",
        )
        self.client.force_login(self.user)
        self.notification = Notification.objects.create(
            recipient=self.user,
            kind=Notification.Kind.NEW_PREDICTION,
            title="Новый прогноз",
            event_key="view:test:1",
        )

    def test_summary_and_mark_read(self):
        summary = self.client.get(reverse("notifications:summary"))
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.json()["unread_count"], 1)

        response = self.client.post(
            reverse("notifications:mark_read", args=[self.notification.id])
        )
        self.assertEqual(response.status_code, 200)
        self.notification.refresh_from_db()
        self.assertTrue(self.notification.is_read)
        self.assertIsNotNone(self.notification.read_at)

    def test_match_watch_toggle(self):
        match = Match.objects.create(
            external_id=991001,
            sync_scope=Match.SyncScope.PREMATCH,
        )
        url = reverse("notifications:match_watch", args=[match.id])

        first = self.client.post(url)
        self.assertEqual(first.status_code, 200)
        self.assertTrue(first.json()["watching"])
        self.assertTrue(MatchWatch.objects.filter(user=self.user, match=match).exists())

        second = self.client.post(url)
        self.assertEqual(second.status_code, 200)
        self.assertFalse(second.json()["watching"])
        self.assertFalse(MatchWatch.objects.filter(user=self.user, match=match).exists())
