from django.test import TestCase
from django.urls import reverse

from cabinet.models import User
from game.models import Match

from .models import MatchWatch, Notification, TelegramAccount
from .services import create_notification, get_preferences
from .telegram_bot import consume_link_payload, create_link_payload, disconnect_telegram


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


class TelegramLinkingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="telegram-reader",
            password="test-password-123",
        )

    def test_deep_link_connects_telegram_and_is_single_use(self):
        payload = create_link_payload(self.user)
        linked_user = consume_link_payload(
            payload,
            chat_id="123456789",
            telegram_username="cappers_user",
        )

        self.assertEqual(linked_user, self.user)
        preferences = get_preferences(self.user)
        telegram_account = TelegramAccount.objects.get(user=self.user)
        self.assertEqual(telegram_account.chat_id, "123456789")
        self.assertEqual(telegram_account.username, "cappers_user")
        self.assertEqual(preferences.telegram_chat_id, "123456789")
        self.assertEqual(preferences.telegram_username, "cappers_user")
        self.assertTrue(preferences.telegram_enabled)
        self.assertIsNotNone(preferences.telegram_connected_at)

        repeated = consume_link_payload(
            payload,
            chat_id="123456789",
            telegram_username="cappers_user",
        )
        self.assertIsNone(repeated)

    def test_same_chat_moves_to_new_cappers_account(self):
        other = User.objects.create_user(
            username="telegram-reader-two",
            password="test-password-123",
        )
        first_payload = create_link_payload(self.user)
        consume_link_payload(first_payload, chat_id="555", telegram_username="same_chat")

        second_payload = create_link_payload(other)
        consume_link_payload(second_payload, chat_id="555", telegram_username="same_chat")

        first_preferences = get_preferences(self.user)
        second_preferences = get_preferences(other)
        self.assertFalse(TelegramAccount.objects.filter(user=self.user).exists())
        self.assertEqual(TelegramAccount.objects.get(user=other).chat_id, "555")
        self.assertEqual(first_preferences.telegram_chat_id, "")
        self.assertFalse(first_preferences.telegram_enabled)
        self.assertEqual(second_preferences.telegram_chat_id, "555")
        self.assertTrue(second_preferences.telegram_enabled)

    def test_disconnect_clears_telegram_delivery(self):
        payload = create_link_payload(self.user)
        consume_link_payload(payload, chat_id="777", telegram_username="reader")
        disconnect_telegram(self.user)

        preferences = get_preferences(self.user)
        self.assertFalse(TelegramAccount.objects.filter(user=self.user).exists())
        self.assertEqual(preferences.telegram_chat_id, "")
        self.assertEqual(preferences.telegram_username, "")
        self.assertFalse(preferences.telegram_enabled)
        self.assertIsNone(preferences.telegram_connected_at)


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

    def test_telegram_disconnect_view(self):
        preferences = get_preferences(self.user)
        preferences.telegram_chat_id = "999"
        preferences.telegram_enabled = True
        preferences.save(update_fields=["telegram_chat_id", "telegram_enabled", "updated_at"])

        response = self.client.post(reverse("notifications:telegram_disconnect"))
        self.assertEqual(response.status_code, 302)

        preferences.refresh_from_db()
        self.assertFalse(TelegramAccount.objects.filter(user=self.user).exists())
        self.assertEqual(preferences.telegram_chat_id, "")
        self.assertFalse(preferences.telegram_enabled)
