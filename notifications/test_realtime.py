from django.test import TestCase
from django.urls import reverse

from cabinet.models import User

from .models import Notification


class RealtimeNotificationSummaryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="realtime-reader",
            password="test-password-123",
        )
        self.client.force_login(self.user)

    def test_initial_summary_seeds_cursor_without_replaying_old_notifications(self):
        notification = Notification.objects.create(
            recipient=self.user,
            kind=Notification.Kind.MATCH_REMINDER,
            title="Старое уведомление",
            event_key="realtime:old:1",
        )

        response = self.client.get(reverse("notifications:summary"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["unread_count"], 1)
        self.assertEqual(payload["cursor_id"], notification.id)
        self.assertEqual(payload["notifications"], [])

    def test_summary_returns_notifications_created_after_cursor(self):
        first = Notification.objects.create(
            recipient=self.user,
            kind=Notification.Kind.MATCH_REMINDER,
            title="Первое",
            event_key="realtime:first:1",
        )
        second = Notification.objects.create(
            recipient=self.user,
            kind=Notification.Kind.ACHIEVEMENT,
            title="Новое достижение",
            message="Появилось новое событие.",
            url="/notifications/",
            event_key="realtime:second:1",
        )

        response = self.client.get(
            reverse("notifications:summary"),
            {"after_id": first.id},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["cursor_id"], second.id)
        self.assertEqual(len(payload["notifications"]), 1)
        self.assertEqual(payload["notifications"][0]["id"], second.id)
        self.assertEqual(payload["notifications"][0]["title"], "Новое достижение")
        self.assertEqual(payload["notifications"][0]["url"], "/notifications/")

    def test_summary_does_not_leak_other_users_notifications(self):
        other = User.objects.create_user(
            username="realtime-other",
            password="test-password-123",
        )
        own = Notification.objects.create(
            recipient=self.user,
            kind=Notification.Kind.MATCH_REMINDER,
            title="Моё",
            event_key="realtime:own:1",
        )
        Notification.objects.create(
            recipient=other,
            kind=Notification.Kind.MATCH_REMINDER,
            title="Чужое",
            event_key="realtime:other:1",
        )

        response = self.client.get(
            reverse("notifications:summary"),
            {"after_id": own.id},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["notifications"], [])
        self.assertEqual(payload["unread_count"], 1)
