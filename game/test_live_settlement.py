from types import SimpleNamespace

from django.test import SimpleTestCase

from game.models import Prediction
from game.services.live_settlement import live_prediction_state


class LiveSettlementStateTests(SimpleTestCase):
    @staticmethod
    def prediction(market: str, selection: str, outcome_code: str = ""):
        return SimpleNamespace(market=market, selection=selection, outcome_code=outcome_code)

    def test_under_total_loses_once_line_is_crossed_with_margin(self):
        prediction = self.prediction("total", "ТМ 2.5")
        self.assertIsNone(live_prediction_state(prediction, (0, 3)))
        self.assertEqual(
            live_prediction_state(prediction, (1, 3)),
            Prediction.StateStatus.LOSE,
        )

    def test_over_total_wins_once_line_is_crossed_with_margin(self):
        prediction = self.prediction("total", "ТБ 2.5")
        # A single goal over the line could still be cancelled by VAR.
        self.assertIsNone(live_prediction_state(prediction, (2, 1)))
        self.assertEqual(
            live_prediction_state(prediction, (2, 2)),
            Prediction.StateStatus.WIN,
        )

    def test_total_waits_while_result_can_still_change(self):
        self.assertIsNone(
            live_prediction_state(self.prediction("total", "ТМ 2.5"), (1, 1))
        )
        self.assertIsNone(
            live_prediction_state(self.prediction("total", "ТБ 2.5"), (1, 1))
        )

    def test_both_score_needs_a_spare_goal_for_each_team(self):
        yes = self.prediction("both_score", "Обе забьют: да")
        no = self.prediction("both_score", "Обе забьют: нет")
        self.assertIsNone(live_prediction_state(yes, (1, 2)))
        self.assertIsNone(live_prediction_state(no, (1, 1)))
        self.assertEqual(live_prediction_state(yes, (2, 2)), Prediction.StateStatus.WIN)
        self.assertEqual(live_prediction_state(no, (2, 3)), Prediction.StateStatus.LOSE)

    def test_basketball_uses_wider_margin(self):
        prediction = self.prediction("total", "ТБ 160.5", "over 160.5")
        self.assertIsNone(live_prediction_state(prediction, (80, 82), sport_code="basketball"))
        self.assertEqual(
            live_prediction_state(prediction, (82, 82), sport_code="basketball"),
            Prediction.StateStatus.WIN,
        )

    def test_outcome_code_is_used_when_present(self):
        prediction = self.prediction("total", "любой текст", "under 2.5")
        self.assertEqual(
            live_prediction_state(prediction, (2, 2)),
            Prediction.StateStatus.LOSE,
        )

    def test_non_irreversible_market_is_not_settled_live(self):
        prediction = self.prediction("winner", "Ничья")
        self.assertIsNone(live_prediction_state(prediction, (1, 1)))
