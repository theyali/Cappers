from types import SimpleNamespace

from django.test import TestCase
from django.urls import reverse

from back.content_view import CONTENT_VIEW_SESSION_KEY, group_by_sport_and_league


class ContentViewModeTests(TestCase):
    def test_view_mode_is_saved_in_session(self):
        response = self.client.get(reverse("front:content_view_state"), {"mode": "table"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["mode"], "table")
        self.assertEqual(self.client.session[CONTENT_VIEW_SESSION_KEY], "table")

    def test_invalid_view_mode_is_rejected(self):
        response = self.client.get(reverse("front:content_view_state"), {"mode": "cards"})

        self.assertEqual(response.status_code, 400)

    def test_items_are_grouped_by_sport_and_league(self):
        sport = SimpleNamespace(pk=1, code="tennis", name_ru="Теннис", name="Tennis")
        league = SimpleNamespace(pk=10, name_ru="ATP", name="ATP", logo="", country=None)
        first = SimpleNamespace(sport=sport, league=league, league_id=10, league_name="ATP", league_country="")
        second = SimpleNamespace(sport=sport, league=league, league_id=10, league_name="ATP", league_country="")

        groups = group_by_sport_and_league([first, second])

        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["code"], "tennis")
        self.assertEqual(groups[0]["count"], 2)
        self.assertEqual(groups[0]["leagues"][0]["count"], 2)
        self.assertEqual(groups[0]["leagues"][0]["items"], [first, second])
