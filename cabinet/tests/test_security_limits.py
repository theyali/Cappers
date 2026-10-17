import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core import mail
from django.core.cache import cache
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from cabinet.models import User


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

    def test_guest_can_still_open_login_form(self):
        response = self.client.get(reverse("cabinet:login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="username"')

    def test_signed_in_users_skip_login_on_get_and_post(self):
        for role in (User.Role.READER, User.Role.ANALYST):
            self.user.role = role
            self.user.save(update_fields=["role"])
            self.client.force_login(self.user)
            for method in (self.client.get, self.client.post):
                with self.subTest(role=role, method=method.__name__):
                    response = method(reverse("cabinet:login"))
                    self.assertRedirects(response, reverse("cabinet:dashboard"), fetch_redirect_response=False)
                    self.assertEqual(self.client.session["_auth_user_id"], str(self.user.pk))

    def test_signed_in_user_keeps_safe_next_destination(self):
        self.client.force_login(self.user)
        destination = reverse("cabinet:profile") + "?tab=settings"
        response = self.client.get(reverse("cabinet:login"), {"next": destination})
        self.assertRedirects(response, destination, fetch_redirect_response=False)

    def test_unsafe_and_self_referencing_next_fall_back_to_cabinet(self):
        self.client.force_login(self.user)
        for destination in (
            "https://evil.example/", "//evil.example/", reverse("cabinet:login"),
            reverse("cabinet:login") + "?next=/", "http://testserver/cabinet/login/",
            reverse("cabinet:login").rstrip("/"),
        ):
            with self.subTest(next=destination):
                response = self.client.get(reverse("cabinet:login"), {"next": destination})
                self.assertRedirects(response, reverse("cabinet:dashboard"), fetch_redirect_response=False)


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
