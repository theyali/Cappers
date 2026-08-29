from types import SimpleNamespace

from django.test import SimpleTestCase

from game.views import _match_odds_tabs
from game.services.odds import has_odds_payload, match_odds_defaults


class BookmakerOddsParserTests(SimpleTestCase):
    def test_v2_bookmaker_markets_are_normalized_to_match_odds_fields(self):
        payload = {
            "bookmakers": [
                {
                    "id": 1,
                    "name": "Bookmaker",
                    "bets": [
                        {
                            "name": "Match Winner",
                            "values": [
                                {"value": "Home", "odd": "2.10"},
                                {"value": "Draw", "odd": "3.20"},
                                {"value": "Away", "odd": "3.40"},
                            ],
                        },
                        {
                            "name": "Double Chance",
                            "values": [
                                {"value": "1X", "odd": "1.33"},
                                {"value": "X2", "odd": "1.72"},
                            ],
                        },
                        {
                            "name": "Totals",
                            "values": [
                                {"value": "Over", "line": "2.5", "odd": "1.91"},
                                {"value": "Under", "line": "2.5", "odd": "1.89"},
                            ],
                        },
                        {
                            "name": "Handicap",
                            "values": [
                                {"value": "Home", "handicap": "0", "odd": "1.66"},
                                {"value": "Away", "handicap": "0", "odd": "2.24"},
                            ],
                        },
                        {
                            "name": "Corners",
                            "values": [
                                {"value": "Over", "line": "8.5", "odd": "1.80"},
                            ],
                        },
                    ],
                }
            ]
        }

        defaults = match_odds_defaults(payload)

        self.assertTrue(has_odds_payload(payload))
        self.assertEqual(defaults["home_win_bet"], 2.10)
        self.assertEqual(defaults["x_bet"], 3.20)
        self.assertEqual(defaults["away_win_bet"], 3.40)
        self.assertEqual(defaults["d_1x"], 1.33)
        self.assertEqual(defaults["d_2x"], 1.72)
        self.assertEqual(defaults["goals_over_2_5"], 1.91)
        self.assertEqual(defaults["goals_under_2_5"], 1.89)
        self.assertEqual(defaults["fora_1_0"], 1.66)
        self.assertEqual(defaults["fora_2_0"], 2.24)
        self.assertEqual(defaults["extra_markets"]["Corners"]["Over 8.5"], 1.80)

    def test_legacy_flat_payload_still_works(self):
        defaults = match_odds_defaults({"home_win_bet": "1.70", "totals_all": {"Over 2.5": "1.90"}})

        self.assertEqual(defaults["home_win_bet"], 1.70)
        self.assertEqual(defaults["totals_all"], {"Over 2.5": 1.90})

    def test_nested_sport_payload_markets_are_exposed_for_match_page(self):
        payload = {
            "home_win_bet": "1.79",
            "x_bet": "4.40",
            "away_win_bet": "3.72",
            "totals_all": {
                "ah": {
                    "0": {"line": "0", "home": 1.36, "away": 2.71},
                    "-1.5": {"line": "-1.5", "home": 2.285, "away": 1.625},
                },
                "total": {
                    "5.5": {"line": "5.5", "over": 1.99, "under": 1.816},
                    "6.5": {"line": "6.5", "over": 2.75, "under": 1.35},
                },
                "melbet": {
                    "markets": {
                        "type_4": {
                            "name": "1X",
                            "values": [{"value": "1X", "odd": 1.292, "handicap": 0}],
                        },
                        "type_5": {
                            "name": "12",
                            "values": [{"value": "12", "odd": 1.227, "handicap": 0}],
                        },
                        "type_6": {
                            "name": "2X",
                            "values": [{"value": "2X", "odd": 2.045, "handicap": 0}],
                        },
                        "type_180": {
                            "name": "Both Teams To Score - Yes",
                            "values": [{"value": "Yes", "odd": 1.80}],
                        },
                        "individual_total_1": {
                            "name": "Individual Total 1",
                            "values": [{"value": "Over", "handicap": 2.5, "odd": 1.52}],
                        },
                    }
                },
                "melbet_individual_total_2": {
                    "2.5": {"line": "2.5", "over": 2.27, "under": 1.59},
                },
            },
        }

        defaults = match_odds_defaults(payload)

        self.assertEqual(defaults["home_win_bet"], 1.79)
        self.assertEqual(defaults["x_bet"], 4.40)
        self.assertEqual(defaults["away_win_bet"], 3.72)
        self.assertEqual(defaults["totals_all"]["Over 5.5"], 1.99)
        self.assertEqual(defaults["totals_all"]["Under 6.5"], 1.35)
        self.assertEqual(defaults["handicaps_all"]["Home 0"], 1.36)
        self.assertEqual(defaults["handicaps_all"]["Away +1.5"], 1.625)
        self.assertEqual(defaults["fora_1_0"], 1.36)
        self.assertEqual(defaults["fora_2_0"], 2.71)
        self.assertEqual(defaults["d_1x"], 1.292)
        self.assertEqual(defaults["d_2x"], 2.045)
        self.assertEqual(defaults["double_chance_all"]["12"], 1.227)
        self.assertEqual(defaults["btts_yes"], 1.80)
        self.assertIn("Individual Total 1", defaults["team_totals_all"])
        self.assertIn("melbet_individual_total_2", defaults["team_totals_all"])


class MatchOddsTabsTests(SimpleTestCase):
    def test_live_match_with_odds_still_exposes_readonly_tabs(self):
        odds = SimpleNamespace(
            home_win_bet=2.10,
            x_bet=3.20,
            away_win_bet=3.40,
            goals_over_2_5=1.91,
            goals_under_2_5=1.89,
            fora_1_0=1.66,
            fora_2_0=2.24,
            btts_yes=1.80,
            btts_no=2.00,
            d_1x=1.33,
            d_2x=1.72,
            first_time_home_win_bet=None,
            first_time_x_bet=None,
            first_time_away_win_bet=None,
            totals_all={"Over 3.5": 2.30, "Under 3.5": 1.60},
            double_chance_all={},
            handicaps_all={},
            btts_all={},
            team_totals_all={},
            first_half_totals_all={},
            first_half_handicaps_all={},
            half_time_full_time_all={},
            exact_score_all={},
            extra_markets={},
        )
        match = SimpleNamespace(
            sync_scope="live",
            odds=odds,
            home_team_name="Home Team",
            away_team_name="Away Team",
        )

        tabs = _match_odds_tabs(match)

        self.assertTrue(tabs)
        self.assertIn("Популярное", [tab["label"] for tab in tabs])
        self.assertIn("Тоталы", [tab["label"] for tab in tabs])
