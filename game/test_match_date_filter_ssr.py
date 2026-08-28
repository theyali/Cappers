from datetime import timedelta

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

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
            reverse("game:match_list"),
            {
                "scope": Match.SyncScope.PREMATCH,
                "date": selected_date.isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["previous_date_iso"], previous_date.isoformat())
        self.assertEqual(
            response.context["next_date_iso"],
            (selected_date + timedelta(days=1)).isoformat(),
        )
        self.assertIn(
            f"scope={Match.SyncScope.PREMATCH}",
            response.context["previous_date_url"],
        )
        self.assertIn(
            f"date={previous_date.isoformat()}",
            response.context["previous_date_url"],
        )

        html = response.content.decode("utf-8")
        date_filter_marker = '<section class="matches-date-filter"'
        matches_shell_marker = 'class="matches-shell"'

        self.assertIn(date_filter_marker, html)
        self.assertIn('data-match-date-input', html)
        self.assertIn(f'value="{selected_date.isoformat()}"', html)
        self.assertLess(html.index(date_filter_marker), html.index(matches_shell_marker))
        self.assertNotIn('data-match-date-filter', html)
