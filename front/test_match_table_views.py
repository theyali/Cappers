import json
from types import SimpleNamespace

from django.contrib.auth.models import AnonymousUser
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse

from front.match_table_views import MAX_TABLE_ODDS_BATCH, _match_ids, match_table_odds


class MatchTableOddsTests(SimpleTestCase):
    def test_match_ids_are_unique_valid_and_bounded(self):
        raw = ",".join(["1", "1", "bad", "0"] + [str(value) for value in range(2, 60)])

        result = _match_ids(raw)

        self.assertEqual(len(result), MAX_TABLE_ODDS_BATCH)
        self.assertEqual(result[0], 1)
        self.assertEqual(result[1], 2)
        self.assertEqual(len(result), len(set(result)))
        self.assertNotIn(0, result)

    def test_empty_odds_request_does_not_touch_database(self):
        request = RequestFactory().get(reverse("front:match_table_odds"))
        request.user = AnonymousUser()

        response = match_table_odds(request)
        payload = json.loads(response.content.decode("utf-8"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload, {"ok": True, "items": {}})

    def test_locked_table_odds_use_lock_icon_instead_of_dash(self):
        match = SimpleNamespace(
            sport_code="football",
            sync_scope="prematch",
            home_team_name="Home",
            away_team_name="Away",
        )

        html = render_to_string(
            "game/includes/_match_table_odds_buttons.html",
            {"match": match, "can_write_coupon": True},
        )

        self.assertIn("match-odd-lock", html)
        self.assertIn("is-locked-odd", html)
        self.assertNotIn("—", html)

    def test_live_table_odds_keep_value_and_show_lock_icon(self):
        odds = SimpleNamespace(
            home_win_bet=1.80,
            x_bet=3.20,
            away_win_bet=4.10,
            goals_over_2_5=1.91,
            goals_under_2_5=1.89,
            btts_yes=1.75,
            totals_all={},
            handicaps_all={},
        )
        match = SimpleNamespace(
            sport_code="football",
            sync_scope="live",
            home_team_name="Home",
            away_team_name="Away",
            odds=odds,
        )

        html = render_to_string(
            "game/includes/_match_table_odds_buttons.html",
            {"match": match, "can_write_coupon": True},
        )

        self.assertIn("match-odd-lock", html)
        self.assertIn("1.80", html)
        self.assertNotIn("data-bet-option", html)
