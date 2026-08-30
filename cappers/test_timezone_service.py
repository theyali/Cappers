from django.test import RequestFactory, SimpleTestCase, override_settings
from django.utils import timezone

from cappers.timezone_service import (
    TIMEZONE_COOKIE,
    activate_request_timezone,
    deactivate_request_timezone,
    safe_timezone_name,
)


@override_settings(TIME_ZONE="Asia/Baku")
class TimezoneServiceTests(SimpleTestCase):
    def test_safe_timezone_name_accepts_iana_timezone(self):
        self.assertEqual(safe_timezone_name("Europe/Moscow"), "Europe/Moscow")

    def test_safe_timezone_name_falls_back_to_settings_timezone(self):
        self.assertEqual(safe_timezone_name("bad/timezone"), "Asia/Baku")

    def test_activate_request_timezone_uses_cookie(self):
        request = RequestFactory().get("/")
        request.COOKIES[TIMEZONE_COOKIE] = "Europe/Moscow"

        try:
            timezone_name = activate_request_timezone(request)

            self.assertEqual(timezone_name, "Europe/Moscow")
            self.assertEqual(request.user_timezone_name, "Europe/Moscow")
            self.assertEqual(timezone.get_current_timezone_name(), "Europe/Moscow")
        finally:
            deactivate_request_timezone()
