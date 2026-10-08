import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from cabinet.models import User
from cabinet.telegram_auth import TELEGRAM_APP_SESSION_KEY

BOT_TOKEN = "123456:TEST-MINI-APP"
TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


def signed_init_data(telegram_id: int) -> str:
    """Launch data signed the way Telegram signs it for a Mini App."""
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAH-test",
        "user": json.dumps({"id": telegram_id, "first_name": "Mini"}, separators=(",", ":")),
    }
    check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


@override_settings(TG_BOT_TOKEN=BOT_TOKEN, STORAGES=TEST_STORAGES)
class TelegramMiniAppShellTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()
        super().tearDown()

    def sign_in_through_mini_app(self):
        return self.client.post(
            reverse("cabinet:telegram_webapp_login"),
            {"init_data": signed_init_data(777000111), "next": "/"},
        )

    def test_mini_app_login_marks_the_session(self):
        response = self.sign_in_through_mini_app()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertTrue(self.client.session[TELEGRAM_APP_SESSION_KEY])

    def test_pages_render_the_telegram_shell_after_mini_app_login(self):
        self.sign_in_through_mini_app()

        response = self.client.get(reverse("front:index"))

        self.assertContains(response, "is-telegram-app")
        self.assertContains(response, 'class="telegram-app-header"')
        self.assertContains(response, "front/js/telegram-app.js")
        self.assertContains(response, "telegram.org/js/telegram-web-app.js")
        self.assertNotContains(response, 'class="site-topbar"')
        self.assertNotContains(response, 'class="site-header"')
        self.assertNotContains(response, "site-footer")

    def test_regular_site_keeps_its_header(self):
        user = User.objects.create_user(username="web-reader", password="x", role=User.Role.READER)
        self.client.force_login(user)

        response = self.client.get(reverse("front:index"))

        self.assertNotContains(response, "is-telegram-app")
        self.assertNotContains(response, "telegram-app-header")
        self.assertNotContains(response, "telegram-web-app.js")
        self.assertContains(response, 'class="site-header"')

    def test_login_page_does_not_wait_for_telegram_org(self):
        response = self.client.get(reverse("cabinet:telegram_webapp_login"), {"next": "/cabinet/"})

        self.assertContains(response, "front/js/telegram-webapp-login.js")
        self.assertContains(response, 'data-next="/cabinet/"')
        self.assertNotContains(response, "telegram.org")
