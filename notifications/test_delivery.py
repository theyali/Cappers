from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from cabinet.models import User
from notifications.models import Notification
from notifications.services import get_preferences
from notifications.tasks import DELIVERY_MAX_ATTEMPTS, _claim_pending_notifications, deliver_pending_notifications


@override_settings(TELEGRAM_BOT_TOKEN="")
class NotificationDeliveryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="notify-user", password="safe-test-password", email="notify@example.com")
        preferences = get_preferences(self.user)
        preferences.email_enabled = True
        preferences.save(update_fields=["email_enabled"])
        self.counter = 0

    def _notification(self, user=None):
        self.counter += 1
        return Notification.objects.create(
            recipient=user or self.user,
            kind=Notification.Kind.NEW_FOLLOWER,
            title="Новый подписчик",
            message="На вас подписались",
            event_key=f"delivery-test:{self.counter}",
        )

    def _make_due(self):
        Notification.objects.update(next_delivery_at=timezone.now() - timedelta(seconds=1))

    def test_email_is_sent_once(self):
        notification = self._notification()

        deliver_pending_notifications()
        deliver_pending_notifications()

        self.assertEqual(len(mail.outbox), 1)
        notification.refresh_from_db()
        self.assertIsNotNone(notification.email_sent_at)
        self.assertIsNotNone(notification.telegram_processed_at)
        self.assertIsNone(notification.next_delivery_at)

    def test_failed_delivery_backs_off_and_is_dropped_after_the_limit(self):
        notification = self._notification()

        with patch("notifications.tasks.send_mail", side_effect=OSError("SMTP down")) as send:
            with self.assertLogs("notifications.tasks", level="ERROR"):
                deliver_pending_notifications()
            notification.refresh_from_db()
            self.assertEqual(notification.delivery_attempts, 1)
            self.assertIsNone(notification.email_processed_at)
            self.assertAlmostEqual(
                notification.next_delivery_at,
                timezone.now() + timedelta(minutes=2),
                delta=timedelta(seconds=30),
            )

            # Waiting for the backoff: the next run does not retry it.
            deliver_pending_notifications()
            self.assertEqual(send.call_count, 1)

            for _ in range(DELIVERY_MAX_ATTEMPTS - 1):
                self._make_due()
                with self.assertLogs("notifications.tasks", level="ERROR"):
                    deliver_pending_notifications()

        notification.refresh_from_db()
        self.assertEqual(notification.delivery_attempts, DELIVERY_MAX_ATTEMPTS)
        self.assertIsNotNone(notification.email_processed_at)
        self.assertIsNone(notification.email_sent_at)
        self.assertEqual(send.call_count, DELIVERY_MAX_ATTEMPTS)

    def test_failing_notifications_do_not_block_the_queue(self):
        for _ in range(3):
            self._notification()
        fresh = self._notification()

        with patch("notifications.tasks.send_mail", side_effect=OSError("SMTP down")):
            with self.assertLogs("notifications.tasks", level="ERROR"):
                deliver_pending_notifications(limit=3)

        deliver_pending_notifications(limit=3)

        fresh.refresh_from_db()
        self.assertIsNotNone(fresh.email_sent_at)

    def test_telegram_without_bot_token_does_not_keep_notification_pending(self):
        preferences = get_preferences(self.user)
        preferences.email_enabled = False
        preferences.telegram_enabled = True
        preferences.telegram_chat_id = "123456"
        preferences.save()
        notification = self._notification()

        deliver_pending_notifications()

        notification.refresh_from_db()
        self.assertIsNotNone(notification.telegram_processed_at)
        self.assertIsNone(notification.telegram_sent_at)

    def test_overlapping_run_skips_claimed_notifications(self):
        self._notification()
        _claim_pending_notifications(300, timezone.now())

        result = deliver_pending_notifications()

        self.assertEqual(result["email_sent"], 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_preferences_are_loaded_in_bulk(self):
        users = [
            User.objects.create_user(username=f"bulk-{index}", password="safe-test-password", email=f"bulk{index}@example.com")
            for index in range(5)
        ]
        for user in users:
            get_preferences(user)
            self._notification(user)

        # Claim (savepoint, select, update, release) + notifications with recipients
        # + preferences + Telegram accounts, then one save per notification.
        with self.assertNumQueries(7 + 5):
            deliver_pending_notifications()
