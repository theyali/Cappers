from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone

from back.content_view import CONTENT_VIEW_SESSION_KEY
from game.models import Match


TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(STORAGES=TEST_STORAGES)
class MatchDateFilterSSRTests(TestCase):
    def test_date_filter_is_present_in_initial_server_html(self):
        selected_date = timezone.localdate() + timedelta(days=3)
        previous_date = selected_date - timedelta(days=1)

        response = self.client.get(
            f"/games/all/{Match.SyncScope.PREMATCH}/{selected_date.isoformat()}/"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["previous_date_iso"], previous_date.isoformat())
        self.assertEqual(
            response.context["next_date_iso"],
            (selected_date + timedelta(days=1)).isoformat(),
        )
        self.assertIn(
            f"/games/all/{Match.SyncScope.PREMATCH}/{previous_date.isoformat()}/",
            response.context["previous_date_url"],
        )

        html = response.content.decode("utf-8")
        date_filter_marker = '<section class="matches-date-filter"'
        matches_shell_marker = 'class="matches-shell"'

        self.assertIn(date_filter_marker, html)
        self.assertIn('class="matches-table-filter-sidebar"', html)
        self.assertIn('class="matches-table-scope-list"', html)
        self.assertIn('class="matches-table-sport-list"', html)
        self.assertIn('Статусы матчей', html)
        self.assertIn('Идут сейчас', html)
        self.assertIn('Предстоящие', html)
        self.assertIn('Завершенные', html)
        self.assertEqual(html.count("data-match-date-input"), 2)
        self.assertIn(f'value="{selected_date.isoformat()}"', html)
        self.assertLess(html.index(date_filter_marker), html.index(matches_shell_marker))
        self.assertNotIn('data-match-date-filter', html)

    def test_saved_table_mode_is_rendered_without_filter_layout_flash(self):
        session = self.client.session
        session[CONTENT_VIEW_SESSION_KEY] = "table"
        session.save()

        selected_date = timezone.localdate()
        response = self.client.get(
            f"/games/all/{Match.SyncScope.PREMATCH}/{selected_date.isoformat()}/"
        )

        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn('class="matches-page is-table-view"', html)
        self.assertIn('data-content-view-current="table"', html)
        self.assertIn('class="matches-table-filter-sidebar"', html)
        self.assertIn('class="matches-table-scope-link is-active"', html)
