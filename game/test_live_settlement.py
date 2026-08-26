from types import SimpleNamespace

from django.test import SimpleTestCase

from game.models import Prediction
from game.services.live_settlement import live_prediction_state


class LiveSettlementStateTests(SimpleTestCase):
    @staticmethod
    def prediction(market: str, selection: str):
        return SimpleNamespace(market=market, selection=selection)

    def test_under_total_loses_as_soon_as_line_is_crossed(self):
        prediction = self.prediction("total", "ТМ 2.5")
        self.assertEqual(
            live_prediction_state(prediction, (0, 3)),
            Prediction.StateStatus.LOSE,
        )

    def test_over_total_wins_as_soon_as_line_is_crossed(self):
        prediction = self.prediction("total", "ТБ 2.5")
        self.assertEqual(
            live_prediction_state(prediction, (2, 1)),
            Prediction.StateStatus.WIN,
        )

    def test_total_waits_while_result_can_still_change(self):
        self.assertIsNone(
            live_prediction_state(self.prediction("total", "ТМ 2.5"), (1, 1))
        )
        self.assertIsNone(
            live_prediction_state(self.prediction("total", "ТБ 2.5"), (1, 1))
        )

    def test_both_score_yes_wins_immediately_after_both_score(self):
        prediction = self.prediction("both_score", "Обе забьют: да")
        self.assertEqual(
            live_prediction_state(prediction, (1, 2)),
            Prediction.StateStatus.WIN,
        )

    def test_both_score_no_loses_immediately_after_both_score(self):
        prediction = self.prediction("both_score", "Обе забьют: нет")
        self.assertEqual(
            live_prediction_state(prediction, (1, 1)),
            Prediction.StateStatus.LOSE,
        )

    def test_non_irreversible_market_is_not_settled_live(self):
        prediction = self.prediction("winner", "Ничья")
        self.assertIsNone(live_prediction_state(prediction, (1, 1)))
