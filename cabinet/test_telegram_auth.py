import hashlib
import hmac
import time

from django.test import TestCase, override_settings
from django.urls import reverse

from notifications.models import NotificationPreference, TelegramAccount

from .models import User


@override_settings(
    TG_BOT_TOKEN="123456:test-token",
    TELEGRAM_AUTH_MAX_AGE=900,
)
class TelegramAuthTests(TestCase):
    def _signed_payload(self, **overrides):
        payload = {
            "id": "987654321",
            "first_name": "Ali",
            "last_name": "Telegram",
            "username": "ali_tg",
            "auth_date": str(int(time.time())),
        }
        payload.update(overrides)
        data_check_string = "\n".join(
            f"{key}={value}" for key, value in sorted(payload.items())
        )
        secret_key = hashlib.sha256(b"123456:test-token").digest()
        payload["hash"] = hmac.new(
            secret_key,
            data_check_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return payload

    def test_login_page_uses_custom_telegram_button_and_bot_id_from_token(self):
        response = self.client.get(reverse("cabinet:login"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="telegram-login-button"')
        self.assertContains(response, 'const botId = "123456";')
        self.assertContains(response, "Telegram.Login.auth")
        self.assertContains(response, 'request_access: "write"')
        self.assertContains(response, reverse("cabinet:telegram_login"))
        self.assertNotContains(response, "data-telegram-login")

    def test_valid_telegram_payload_creates_user_and_notification_link(self):
        response = self.client.get(
            reverse("cabinet:telegram_login"),
            self._signed_payload(),
        )

        self.assertRedirects(response, reverse("cabinet:dashboard"))
        user = User.objects.get(telegram_id=987654321)
        self.assertEqual(user.telegram_username, "ali_tg")
        self.assertFalse(user.has_usable_password())
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

        account = TelegramAccount.objects.get(user=user)
        self.assertEqual(account.chat_id, "987654321")
        self.assertEqual(account.username, "ali_tg")
        self.assertEqual(account.first_name, "Ali")
        self.assertEqual(account.last_name, "Telegram")

        preferences = NotificationPreference.objects.get(user=user)
        self.assertEqual(preferences.telegram_chat_id, "987654321")
        self.assertEqual(preferences.telegram_username, "ali_tg")
        self.assertIsNotNone(preferences.telegram_connected_at)
        self.assertTrue(preferences.telegram_enabled)

    def test_existing_manual_telegram_link_is_reused_instead_of_new_user(self):
        existing_user = User.objects.create_user(
            username="existing_user",
            password="test-password-123",
            first_name="Old",
        )
        TelegramAccount.objects.create(
            user=existing_user,
            chat_id="987654321",
            username="old_username",
        )

        response = self.client.get(
            reverse("cabinet:telegram_login"),
            self._signed_payload(),
        )

        self.assertRedirects(response, reverse("cabinet:dashboard"))
        existing_user.refresh_from_db()
        self.assertEqual(existing_user.telegram_id, 987654321)
        self.assertEqual(existing_user.telegram_username, "ali_tg")
        self.assertEqual(existing_user.first_name, "Ali")
        self.assertEqual(int(self.client.session["_auth_user_id"]), existing_user.pk)
        self.assertEqual(User.objects.filter(telegram_id=987654321).count(), 1)

        account = TelegramAccount.objects.get(user=existing_user)
        self.assertEqual(account.chat_id, "987654321")
        self.assertEqual(account.username, "ali_tg")

    def test_invalid_signature_is_rejected(self):
        payload = self._signed_payload()
        payload["hash"] = "0" * 64

        response = self.client.get(reverse("cabinet:telegram_login"), payload)

        self.assertRedirects(response, reverse("cabinet:login"))
        self.assertFalse(User.objects.filter(telegram_id=987654321).exists())
        self.assertFalse(TelegramAccount.objects.filter(chat_id="987654321").exists())

    def test_expired_payload_is_rejected(self):
        payload = self._signed_payload(auth_date=str(int(time.time()) - 3600))

        response = self.client.get(reverse("cabinet:telegram_login"), payload)

        self.assertRedirects(response, reverse("cabinet:login"))
        self.assertFalse(User.objects.filter(telegram_id=987654321).exists())
        self.assertFalse(TelegramAccount.objects.filter(chat_id="987654321").exists())


@override_settings(TG_BOT_TOKEN="")
class TelegramAuthConfigurationTests(TestCase):
    def test_missing_bot_token_disables_telegram_login(self):
        response = self.client.get(reverse("cabinet:login"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Укажите TG_BOT_TOKEN в окружении.")
        self.assertNotContains(response, 'id="telegram-login-button"')
