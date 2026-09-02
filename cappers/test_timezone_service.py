import re

from django.conf import settings
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.utils import timezone

from cappers.timezone_service import (
    TIMEZONE_COOKIE,
    activate_request_timezone,
    deactivate_request_timezone,
    safe_timezone_name,
)
from cappers.user_context_middleware import _html_injection


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

    def test_browser_context_script_disables_late_browser_autorestore(self):
        script_path = settings.BASE_DIR / "front/static/front/js/browser-context.js"
        script = script_path.read_text(encoding="utf-8")

        self.assertIn("scrollRestoration", script)
        self.assertIn('"manual"', script)
        self.assertIn("data-scroll-restoring", script)

    def test_global_script_injection_uses_external_files_only(self):
        markup = _html_injection().decode("utf-8")

        self.assertIn('src="/static/front/js/browser-context.js"', markup)
        self.assertIn('src="/static/front/js/match-timing.js"', markup)
        self.assertNotIn("<script>", markup)
        self.assertNotIn("CAPPERS_MATCH_TIMING_URL", markup)

    def test_frontend_javascript_does_not_use_string_evaluation(self):
        js_root = settings.BASE_DIR / "front/static/front/js"
        forbidden_literals = ("eval(", "new Function(")
        string_timer = re.compile(r"\bset(?:Timeout|Interval)\s*\(\s*(['\"])" )

        violations = []
        for script_path in sorted(js_root.glob("*.js")):
            script = script_path.read_text(encoding="utf-8")
            for literal in forbidden_literals:
                if literal in script:
                    violations.append(f"{script_path.name}: {literal}")
            if string_timer.search(script):
                violations.append(f"{script_path.name}: string timer")

        self.assertEqual(violations, [], "Unsafe JavaScript evaluation found: " + ", ".join(violations))
