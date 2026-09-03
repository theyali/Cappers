from types import SimpleNamespace

from django.test import SimpleTestCase

from game.models import Prediction
from game.services.settlement import prediction_state


class SettlementStateTests(SimpleTestCase):
    @staticmethod
    def prediction(market: str, selection: str):
        return SimpleNamespace(
            market=market,
            selection=selection,
            match=SimpleNamespace(
                home_team_name="Хозяева",
                away_team_name="Гости",
                raw_data={},
            ),
        )

    def test_hockey_total_over_5_5_wins_on_4_3_score(self):
        result = {
            "home_goals": 4,
            "away_goals": 3,
            "winning": [],
            "refunds": [],
        }

        state = prediction_state(self.prediction("total", "ТБ 5.5"), result)

        self.assertEqual(state, Prediction.StateStatus.WIN)

    def test_human_total_market_name_is_supported(self):
        result = {
            "home_goals": 4,
            "away_goals": 3,
            "winning": [],
            "refunds": [],
        }

        state = prediction_state(self.prediction("Тотал", "Over 5.5"), result)

        self.assertEqual(state, Prediction.StateStatus.WIN)

    def test_total_can_use_period_scores_for_non_football_sports(self):
        prediction = self.prediction("total", "ТБ 22.5")
        prediction.match.raw_data = {
            "sets": {
                "set_1": "7-6",
                "set_2": "6-4",
            }
        }
        result = {
            "home_goals": 2,
            "away_goals": 0,
            "winning": [],
            "refunds": [],
        }

        state = prediction_state(prediction, result)

        self.assertEqual(state, Prediction.StateStatus.WIN)
