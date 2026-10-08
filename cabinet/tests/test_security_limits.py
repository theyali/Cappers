import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from cabinet.models import User
from cabinet.telegram_auth import _telegram_oauth_url


TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


class ProductionSettingsTests(SimpleTestCase):
    def _import_settings(self, **env):
        return subprocess.run(
            [sys.executable, "-c", "import cappers.settings"],
            cwd=Path(settings.BASE_DIR),
            env={**os.environ, **env},
            capture_output=True,
            text=True,
        )

    def test_production_refuses_to_start_without_secret_key(self):
        for secret_key in ("", "change-me-in-production"):
            with self.subTest(secret_key=secret_key):
                result = self._import_settings(DEBUG="False", SECRET_KEY=secret_key)

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Set SECRET_KEY", result.stderr)

    def test_debug_is_off_unless_enabled(self):
        env = {key: value for key, value in os.environ.items() if key != "DEBUG"}
        result = subprocess.run(
            [sys.executable, "-c", "import cappers.settings as s; print(s.DEBUG, s.SESSION_COOKIE_SECURE)"],
            cwd=Path(settings.BASE_DIR),
            env={**env, "SECRET_KEY": "test-production-secret"},
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.stdout.strip(), "False True")

    def test_https_from_nginx_is_recognized(self):
        request = RequestFactory().get("/", HTTP_X_FORWARDED_PROTO="https")

        self.assertTrue(request.is_secure())
        self.assertTrue(request.build_absolute_uri("/pay/return/").startswith("https://"))

    @override_settings(
        SITE_BASE_URL="https://capper-hub.com",
        TG_BOT_TOKEN="8842559788:test-token",
    )
    def test_telegram_oauth_url_uses_site_base_url(self):
        url = _telegram_oauth_url("/cabinet/login/telegram/")
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)

        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "oauth.telegram.org")
        self.assertEqual(query["bot_id"], ["8842559788"])
        self.assertEqual(query["origin"], ["https://capper-hub.com"])
        self.assertEqual(query["return_to"], ["https://capper-hub.com/cabinet/login/telegram/"])


@override_settings(STORAGES=TEST_STORAGES)
class LoginLimitTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="limit-user", password="safe-test-password")
        cache.delete("ratelimit:login-failures:127.0.0.1:limit-user")

    def _login(self, password):
        return self.client.post(reverse("cabinet:login"), {"username": "limit-user", "password": password})

    def test_password_guessing_is_stopped(self):
        for _ in range(10):
            self.assertEqual(self._login("wrong-password").status_code, 200)

        response = self._login("safe-test-password")

        self.assertContains(response, "Слишком много неудачных попыток входа")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_successful_login_is_not_counted(self):
        for _ in range(12):
            self.client.logout()
            self.assertEqual(self._login("safe-test-password").status_code, 302)


class PasswordResetLimitTests(TestCase):
    def test_reset_emails_are_limited_per_account(self):
        User.objects.create_user(username="reset-user", password="safe-test-password", email="reset@example.com")

        for _ in range(5):
            response = self.client.post(reverse("cabinet:password_reset"), {"email": "reset@example.com"})
            self.assertEqual(response.status_code, 302)

        self.assertEqual(len(mail.outbox), 3)


class CouponPublishLimitTests(TestCase):
    def test_publishing_is_rate_limited(self):
        analyst = User.objects.create_user(
            username="publish-limit-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        cache.delete(f"ratelimit:coupon-publish:{analyst.pk}")
        self.client.force_login(analyst)
        payload = json.dumps({"items": []})

        with patch("game.services.coupon_validation.COUPON_PUBLISHES_PER_MINUTE", 2):
            statuses = [
                self.client.post(reverse("game:create_coupon"), payload, content_type="application/json").status_code
                for _ in range(3)
            ]
            autosave = self.client.post(
                reverse("game:create_coupon"),
                json.dumps({"items": [], "autosave": True}),
                content_type="application/json",
            )

        self.assertEqual(statuses, [400, 400, 429])
        self.assertNotEqual(autosave.status_code, 429)
