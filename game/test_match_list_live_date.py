from datetime import datetime, time, timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cabinet.models import User
from game.date_views import MATCHES_PAGE_SIZE
from game.models import Match, Sport
from notifications.models import MatchWatch


TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(STORAGES=TEST_STORAGES)
class MatchListLiveDateTests(TestCase):
    def test_sport_filter_limits_matches_and_is_preserved_in_links(self):
        football = Sport.objects.create(code="football", name="Football", name_ru="Футбол")
        basketball = Sport.objects.create(code="basketball", name="Basketball", name_ru="Баскетбол")
        tz = timezone.get_current_timezone()
        selected_date = timezone.localdate()
        starts_at = timezone.make_aware(datetime.combine(selected_date, time(15, 0)), tz)
        football_match = Match.objects.create(
            external_id=919001,
            sport=football,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=starts_at,
        )
        basketball_match = Match.objects.create(
            external_id=919002,
            sport=basketball,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=starts_at + timedelta(minutes=30),
        )

        response = self.client.get(
            reverse("game:match_list"),
            {
                "scope": Match.SyncScope.PREMATCH,
                "date": selected_date.isoformat(),
                "sport": "basketball",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response["Location"],
            f"/games/basketball/{Match.SyncScope.PREMATCH}/{selected_date.isoformat()}/",
        )

        response = self.client.get(response["Location"])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_sport"], "basketball")
        self.assertEqual(
            [match.id for match in response.context["matches"]],
            [basketball_match.id],
        )
        self.assertNotIn(football_match.id, [match.id for match in response.context["matches"]])
        self.assertIn(
            f"/games/basketball/{Match.SyncScope.PREMATCH}/{(selected_date - timedelta(days=1)).isoformat()}/",
            response.context["previous_date_url"],
        )
        prematch_tab = next(
            tab
            for tab in response.context["scope_tabs"]
            if tab["scope"] == Match.SyncScope.PREMATCH
        )
        self.assertIn(
            f"/games/basketball/{Match.SyncScope.PREMATCH}/{selected_date.isoformat()}/",
            prematch_tab["url"],
        )
        basketball_tab = next(
            tab
            for tab in response.context["sport_tabs"]
            if tab["code"] == "basketball"
        )
        self.assertEqual(basketball_tab["count"], 1)
        self.assertIn(
            f"/games/basketball/{Match.SyncScope.PREMATCH}/{selected_date.isoformat()}/",
            basketball_tab["url"],
        )

    def test_live_scope_uses_clean_url_without_date(self):
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

        response = self.client.get(f"/games/all/{Match.SyncScope.LIVE}/{selected_date.isoformat()}/")

        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], "/games/all/live/")

        response = self.client.get(response["Location"])

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
        self.assertEqual(live_tab["url"], "/games/all/live/")
        self.assertFalse(response.context["show_date_filter"])

    def test_query_live_filter_redirects_to_clean_live_url(self):
        selected_date = timezone.localdate()

        response = self.client.get(
            reverse("game:match_list"),
            {
                "scope": Match.SyncScope.LIVE,
                "date": selected_date.isoformat(),
                "sport": "football",
            },
        )

        self.assertEqual(response.status_code, 301)
        self.assertEqual(response["Location"], "/games/football/live/")

    def test_far_match_dates_return_404(self):
        far_date = timezone.localdate() + timedelta(days=31)

        response = self.client.get(f"/games/football/all/{far_date.isoformat()}/")

        self.assertEqual(response.status_code, 404)

    def test_match_filter_seo_is_unique_and_query_pages_are_noindex(self):
        selected_date = timezone.localdate()

        response = self.client.get(f"/games/hockey/{Match.SyncScope.PREMATCH}/{selected_date.isoformat()}/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["match_list_h1"],
            f"Предстоящие матчи по хоккею на {selected_date.strftime('%d.%m.%Y')}",
        )
        self.assertEqual(response.context["seo_meta"]["robots"], "index,follow")
        self.assertIn("Предстоящие матчи по хоккею", response.context["seo_meta"]["title"])

        paged_response = self.client.get(
            f"/games/hockey/{Match.SyncScope.PREMATCH}/{selected_date.isoformat()}/",
            {"page": "2"},
        )

        self.assertEqual(paged_response.status_code, 200)
        self.assertEqual(paged_response.context["seo_meta"]["robots"], "noindex,follow")

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

    def test_ajax_lazy_page_keeps_scope_and_selected_date(self):
        tz = timezone.get_current_timezone()
        selected_date = timezone.localdate()
        starts_at = timezone.make_aware(datetime.combine(selected_date, time(10, 0)), tz)
        matches = [
            Match.objects.create(
                external_id=930000 + index,
                sync_scope=Match.SyncScope.PREMATCH,
                starts_at=starts_at + timedelta(minutes=index),
            )
            for index in range(MATCHES_PAGE_SIZE + 2)
        ]
        Match.objects.create(
            external_id=940000,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=starts_at + timedelta(days=1),
        )
        Match.objects.create(
            external_id=940001,
            sync_scope=Match.SyncScope.FINISHED,
            starts_at=starts_at + timedelta(minutes=5),
        )

        first_response = self.client.get(
            f"/games/all/{Match.SyncScope.PREMATCH}/{selected_date.isoformat()}/"
        )
        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(len(first_response.context["matches"]), MATCHES_PAGE_SIZE)
        self.assertTrue(first_response.context["page_obj"].has_next())

        response = self.client.get(
            f"/games/all/{Match.SyncScope.PREMATCH}/{selected_date.isoformat()}/",
            {
                "page": 2,
                "sort": "starts_at",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["has_next"])
        self.assertIsNone(payload["next_page"])
        self.assertEqual(payload["page"], 2)
        self.assertIn(f'data-match-shell-id="{matches[-2].id}"', payload["html"])
        self.assertIn(f'data-match-shell-id="{matches[-1].id}"', payload["html"])
        self.assertNotIn(f'data-match-shell-id="{matches[0].id}"', payload["html"])

    def test_ajax_window_refresh_reorders_watched_match_without_resetting_filters(self):
        user = User.objects.create_user(username="window-watch-user", password="safe-test-password")
        self.client.force_login(user)
        tz = timezone.get_current_timezone()
        selected_date = timezone.localdate()
        starts_at = timezone.make_aware(datetime.combine(selected_date, time(11, 0)), tz)
        matches = [
            Match.objects.create(
                external_id=950000 + index,
                sync_scope=Match.SyncScope.PREMATCH,
                starts_at=starts_at + timedelta(minutes=index),
            )
            for index in range(MATCHES_PAGE_SIZE + 2)
        ]
        MatchWatch.objects.create(user=user, match=matches[-1], last_scope=Match.SyncScope.PREMATCH)

        response = self.client.get(
            f"/games/all/{Match.SyncScope.PREMATCH}/{selected_date.isoformat()}/",
            {
                "lazy": 1,
                "window": MATCHES_PAGE_SIZE,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["window"], MATCHES_PAGE_SIZE)
        first_marker = payload["html"].find('data-match-shell-id=')
        watched_marker = payload["html"].find(f'data-match-shell-id="{matches[-1].id}"')
        self.assertEqual(first_marker, watched_marker)
        self.assertTrue(payload["has_next"])
        self.assertEqual(payload["next_page"], 2)
