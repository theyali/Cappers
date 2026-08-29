from django.test import SimpleTestCase

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
        self.assertEqual(defaults["totals_all"], {"Over 2.5": "1.90"})
