from types import SimpleNamespace

from django.test import SimpleTestCase

from game.templatetags.coupon_options import build_match_coupon_options


class CouponOptionsBySportTests(SimpleTestCase):
    def _odds(self, **overrides):
        values = {
            "home_win_bet": 1.80,
            "x_bet": 3.20,
            "away_win_bet": 4.10,
            "goals_over_2_5": 1.91,
            "goals_under_2_5": 1.89,
            "fora_1_0": 1.84,
            "fora_2_0": 2.02,
            "btts_yes": 1.75,
            "totals_all": {},
            "handicaps_all": {},
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def _match(self, sport_code, odds):
        return SimpleNamespace(
            sport_code=sport_code,
            home_team_name="Home Team",
            away_team_name="Away Team",
            odds=odds,
        )

    def test_football_keeps_existing_quick_markets(self):
        result = build_match_coupon_options(self._match("football", self._odds()))

        self.assertEqual(
            [item["label"] for item in result["items"]],
            ["1", "X", "2", "ТБ 2.5", "ТМ 2.5", "ОЗ Да"],
        )
        self.assertEqual([item["coefficient"] for item in result["items"]], ["1.80", "3.20", "4.10", "1.91", "1.89", "1.75"])

    def test_hockey_uses_5_5_total_and_home_zero_handicap(self):
        odds = self._odds(
            totals_all={"Over 5.5": 1.87, "Under 5.5": 1.93},
            fora_1_0=1.88,
        )
        result = build_match_coupon_options(self._match("hockey", odds))

        self.assertEqual(
            [item["label"] for item in result["items"]],
            ["П1", "X", "П2", "ТБ 5.5", "ТМ 5.5", "Ф1 0"],
        )
        self.assertEqual([item["coefficient"] for item in result["items"]][-3:], ["1.87", "1.93", "1.88"])

    def test_basketball_uses_160_5_total_and_requested_handicaps(self):
        odds = self._odds(
            x_bet=None,
            totals_all={"Over 160.5": 1.90, "Under 160.5": 1.92},
            handicaps_all={"Home -3.5": 1.86, "Away +3.5": 1.96},
        )
        result = build_match_coupon_options(self._match("basketball", odds))

        self.assertEqual(
            [item["label"] for item in result["items"]],
            ["П1", "П2", "ТБ 160.5", "ТМ 160.5", "Ф1 -3.5", "Ф2 +3.5"],
        )
        self.assertEqual([item["coefficient"] for item in result["items"]][-4:], ["1.90", "1.92", "1.86", "1.96"])

    def test_tennis_uses_22_5_total_and_requested_handicaps(self):
        odds = self._odds(
            x_bet=None,
            totals_all={"Over 22.5": 1.83, "Under 22.5": 2.01},
            handicaps_all={"Home -1.5": 1.94, "Away +1.5": 1.88},
        )
        result = build_match_coupon_options(self._match("tennis", odds))

        self.assertEqual(
            [item["label"] for item in result["items"]],
            ["П1", "П2", "ТБ 22.5", "ТМ 22.5", "Ф1 -1.5", "Ф2 +1.5"],
        )
        self.assertEqual([item["coefficient"] for item in result["items"]][-4:], ["1.83", "2.01", "1.94", "1.88"])
