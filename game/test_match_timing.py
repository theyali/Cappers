import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from cabinet.models import User
from game.models import Match, Sport
from game.services.match_timing import match_timing_payload, prediction_window_open


class MatchTimingTests(TestCase):
    def setUp(self):
        self.sport = Sport.objects.create(
            external_id=92001,
            code="football-timing-test",
            name="Football timing test",
            name_ru="Футбол",
        )

    def _match(self, *, external_id, starts_at, scope=Match.SyncScope.PREMATCH):
        return Match.objects.create(
            external_id=external_id,
            sport=self.sport,
            sync_scope=scope,
            starts_at=starts_at,
            raw_data={
                "teams": {
                    "home": {"name": {"ru": "Хозяева", "en": "Home"}},
                    "away": {"name": {"ru": "Гости", "en": "Away"}},
                },
                "league": {"name": {"ru": "Тестовая лига", "en": "Test league"}},
            },
        )

    def test_match_is_soon_but_prediction_still_open_before_kickoff(self):
        now = datetime(2026, 8, 29, 13, 25, tzinfo=ZoneInfo("UTC"))
        match = self._match(
            external_id=92002,
            starts_at=now + timedelta(minutes=5),
        )

        payload = match_timing_payload(match, now=now)

        self.assertEqual(payload["state"], "soon")
        self.assertEqual(payload["label"], "Скоро начнется")
        self.assertTrue(payload["prediction_open"])
        self.assertTrue(prediction_window_open(match, now=now))

    def test_local_kickoff_closes_prediction_even_if_provider_still_prematch(self):
        now = datetime(2026, 8, 29, 13, 31, tzinfo=ZoneInfo("UTC"))
        match = self._match(
            external_id=92003,
            starts_at=now - timedelta(minutes=1),
        )

        payload = match_timing_payload(match, now=now)

        self.assertEqual(match.sync_scope, Match.SyncScope.PREMATCH)
        self.assertEqual(payload["state"], "soon")
        self.assertTrue(payload["is_overdue"])
        self.assertFalse(payload["prediction_open"])
        self.assertFalse(prediction_window_open(match, now=now))

    def test_coupon_endpoint_rejects_started_match_without_waiting_for_live_api(self):
        analyst = User.objects.create_user(
            username="kickoff-guard",
            password="test-password",
            role=User.Role.ANALYST,
        )
        match = self._match(
            external_id=92004,
            starts_at=timezone.now() - timedelta(minutes=1),
        )
        self.client.force_login(analyst)

        response = self.client.post(
            reverse("game:create_coupon"),
            data=json.dumps(
                {
                    "stake": "100",
                    "confidence": 70,
                    "items": [
                        {
                            "match_id": match.id,
                            "market": "winner",
                            "selection": "Хозяева",
                            "coefficient": "1.80",
                        }
                    ],
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn("уже начался или скоро начнется", response.json()["error"])

    def test_moscow_browser_timezone_renders_baku_1730_as_1630(self):
        # 13:30 UTC = 17:30 in Baku and 16:30 in Moscow on this date.
        starts_at = datetime(2026, 8, 29, 13, 30, tzinfo=ZoneInfo("UTC"))
        self._match(external_id=92005, starts_at=starts_at)
        self.client.cookies["cappers_tz"] = "Europe/Moscow"

        response = self.client.get(
            reverse(
                "game:match_list_filtered",
                kwargs={"sport": "all", "scope": "all", "selected_date": "2026-08-29"},
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "29.08 16:30")
        self.assertNotContains(response, "29.08 17:30")
        self.assertContains(response, "match-timing.js")
        self.assertContains(response, "front/css/main.css")

    def test_timing_endpoint_uses_active_browser_timezone(self):
        match = self._match(
            external_id=92006,
            starts_at=timezone.now() + timedelta(minutes=20),
        )
        self.client.cookies["cappers_tz"] = "Europe/Moscow"

        response = self.client.get(reverse("game:match_timing"), {"ids": str(match.id)})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["timezone"], "Europe/Moscow")
        self.assertIn(str(match.id), response.json()["matches"])
