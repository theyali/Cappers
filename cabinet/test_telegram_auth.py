import hashlib
import hmac
import time

from django.test import TestCase, override_settings
from django.urls import reverse

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
        self.assertContains(response, reverse("cabinet:telegram_login"))
        self.assertNotContains(response, "data-telegram-login")

    def test_valid_telegram_payload_creates_and_logs_in_user(self):
        response = self.client.get(
            reverse("cabinet:telegram_login"),
            self._signed_payload(),
        )

        self.assertRedirects(response, reverse("cabinet:dashboard"))
        user = User.objects.get(telegram_id=987654321)
        self.assertEqual(user.telegram_username, "ali_tg")
        self.assertFalse(user.has_usable_password())
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_invalid_signature_is_rejected(self):
        payload = self._signed_payload()
        payload["hash"] = "0" * 64

        response = self.client.get(reverse("cabinet:telegram_login"), payload)

        self.assertRedirects(response, reverse("cabinet:login"))
        self.assertFalse(User.objects.filter(telegram_id=987654321).exists())

    def test_expired_payload_is_rejected(self):
        payload = self._signed_payload(auth_date=str(int(time.time()) - 3600))

        response = self.client.get(reverse("cabinet:telegram_login"), payload)

        self.assertRedirects(response, reverse("cabinet:login"))
        self.assertFalse(User.objects.filter(telegram_id=987654321).exists())


@override_settings(TG_BOT_TOKEN="")
class TelegramAuthConfigurationTests(TestCase):
    def test_missing_bot_token_disables_telegram_login(self):
        response = self.client.get(reverse("cabinet:login"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Укажите TG_BOT_TOKEN в окружении.")
        self.assertNotContains(response, 'id="telegram-login-button"')
