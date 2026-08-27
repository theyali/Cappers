from datetime import datetime, time, timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cabinet.models import User
from game.models import Match


TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(STORAGES=TEST_STORAGES)
class MatchListLiveDateTests(TestCase):
    def test_live_scope_ignores_selected_calendar_date(self):
        tz = timezone.get_current_timezone()
        selected_date = timezone.localdate()
        selected_day_start = timezone.make_aware(
            datetime.combine(selected_date, time(12, 0)),
            tz,
        )
        live_from_another_day = Match.objects.create(
            external_id=920001,
            sync_scope=Match.SyncScope.LIVE,
            starts_at=selected_day_start - timedelta(days=2),
        )
        Match.objects.create(
            external_id=920002,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=selected_day_start,
        )

        response = self.client.get(
            reverse("game:match_list"),
            {"scope": Match.SyncScope.LIVE, "date": selected_date.isoformat()},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [match.id for match in response.context["matches"]],
            [live_from_another_day.id],
        )
        live_tab = next(
            tab
            for tab in response.context["scope_tabs"]
            if tab["scope"] == Match.SyncScope.LIVE
        )
        self.assertEqual(live_tab["count"], 1)

    def test_prematch_card_without_odds_shows_locked_empty_odds(self):
        user = User.objects.create_user(
            username="oddsless-analyst",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.client.force_login(user)
        tz = timezone.get_current_timezone()
        selected_date = timezone.localdate()
        starts_at = timezone.make_aware(datetime.combine(selected_date, time(19, 0)), tz)
        Match.objects.create(
            external_id=920003,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=starts_at,
        )

        response = self.client.get(reverse("game:match_list"))

        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn("match-card-options", html)
        self.assertIn("match-odd-lock", html)
        self.assertNotIn('data-bet-option data-bet-key="home"', html)
        self.assertNotIn('data-coefficient="2.00"', html)
        self.assertNotIn("<small>2.00</small>", html)
