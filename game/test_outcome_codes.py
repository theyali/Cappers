import json
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from cabinet.models import User
from game.models import Match, MatchManualReview, MatchOdds, Prediction, PredictionCoupon, Sport
from game.services.bet_options import build_match_odds_tabs, match_bet_options
from game.services.odds import outcome_code_from_label
from game.services.settlement import prediction_state, settle_finished_matches


def _match(home="Динамо", away="Динамо Москва", **extra):
    values = {
        "home_team_name": home,
        "away_team_name": away,
        "raw_data": {},
        "sport_id": None,
        "sport_code": "football",
    }
    values.update(extra)
    return SimpleNamespace(**values)


def _prediction(market, selection, outcome_code="", match=None):
    return SimpleNamespace(
        market=market,
        selection=selection,
        outcome_code=outcome_code,
        match=match or _match(),
    )


def _result(home_goals, away_goals):
    return {"home_goals": home_goals, "away_goals": away_goals, "winning": [], "refunds": []}


class LegacyTextSettlementTests(SimpleTestCase):
    """Predictions without an outcome code must not confuse overlapping team names."""

    def test_away_team_whose_name_contains_home_name(self):
        away_bet = _prediction("winner", "Динамо Москва")
        home_bet = _prediction("winner", "Динамо")

        self.assertEqual(prediction_state(away_bet, _result(0, 1)), Prediction.StateStatus.WIN)
        self.assertEqual(prediction_state(home_bet, _result(0, 1)), Prediction.StateStatus.LOSE)

    def test_double_chance_with_overlapping_names(self):
        self.assertEqual(
            prediction_state(_prediction("double_chance", "Ничья или Динамо Москва"), _result(0, 1)),
            Prediction.StateStatus.WIN,
        )
        self.assertEqual(
            prediction_state(_prediction("double_chance", "Динамо или ничья"), _result(0, 1)),
            Prediction.StateStatus.LOSE,
        )

    def test_handicap_with_overlapping_names(self):
        self.assertEqual(
            prediction_state(_prediction("handicap", "Динамо Москва фора +1.5"), _result(1, 0)),
            Prediction.StateStatus.WIN,
        )


class OutcomeCodeSettlementTests(SimpleTestCase):
    def test_codes_settle_every_supported_market(self):
        cases = [
            ("winner", "2", (0, 1), Prediction.StateStatus.WIN),
            ("winner", "X", (0, 1), Prediction.StateStatus.LOSE),
            ("double_chance", "X2", (1, 1), Prediction.StateStatus.WIN),
            ("double_chance", "12", (1, 1), Prediction.StateStatus.LOSE),
            ("total", "over 2.5", (2, 1), Prediction.StateStatus.WIN),
            ("total", "under 3", (2, 1), Prediction.StateStatus.REFUND),
            ("both_score", "no", (2, 0), Prediction.StateStatus.WIN),
            ("handicap", "away +1.5", (1, 0), Prediction.StateStatus.WIN),
            ("handicap", "home 0", (1, 1), Prediction.StateStatus.REFUND),
            ("exact_score", "2:1", (2, 1), Prediction.StateStatus.WIN),
        ]
        for market, code, score, expected in cases:
            with self.subTest(market=market, code=code):
                # The selection text is deliberately misleading: only the code counts.
                prediction = _prediction(market, "Динамо", code)
                self.assertEqual(prediction_state(prediction, _result(*score)), expected)

    def test_tennis_total_ignores_current_point_row(self):
        match = _match(
            sport_code="tennis",
            raw_data={
                "periods": {
                    "items": [
                        {"code": "S1", "type": "set", "score": {"home": "6", "away": "4"}},
                        {"code": "S2", "type": "set", "score": {"home": "6", "away": "3"}},
                        {"code": "POINT", "type": "point", "score": {"home": "40", "away": "30"}},
                    ]
                }
            },
        )
        prediction = _prediction("total", "ТМ 22.5", "under 22.5", match=match)

        self.assertEqual(prediction_state(prediction, _result(2, 0)), Prediction.StateStatus.WIN)


class OutcomeCodeLabelTests(SimpleTestCase):
    def test_provider_label_formats(self):
        self.assertEqual(outcome_code_from_label("handicap", "1 (-1.5)"), "home -1.5")
        self.assertEqual(outcome_code_from_label("handicap", "2 (1.5)"), "away +1.5")
        self.assertEqual(outcome_code_from_label("handicap", "Away +2.5"), "away +2.5")
        self.assertEqual(outcome_code_from_label("exact_score", "Correct Score 3-2 3.002"), "3:2")
        self.assertEqual(outcome_code_from_label("double_chance", "12"), "12")
        self.assertEqual(outcome_code_from_label("total", "Under 160.5"), "under 160.5")
        self.assertEqual(outcome_code_from_label("handicap", "Asian Handicap"), "")


class BetOptionCodesTests(TestCase):
    def _match(self, sport_code):
        external_ids = {"football": 9002, "basketball": 9004}
        sport = Sport.objects.create(external_id=external_ids[sport_code], code=sport_code, name=sport_code)
        return Match.objects.create(
            external_id=775000 + sport.pk,
            sport=sport,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now() + timedelta(hours=2),
            raw_data={"teams": {"home": {"name": {"ru": "Хозяева"}}, "away": {"name": {"ru": "Гости"}}}},
        )

    def test_offered_outcomes_carry_codes(self):
        match = self._match("football")
        MatchOdds.objects.create(
            match=match,
            home_win_bet=1.85,
            x_bet=3.4,
            handicaps_all={"1 (-1.5)": 3.1, "Something odd": 2.0},
        )

        options = match_bet_options(match)

        self.assertEqual(options[("winner", "хозяева")].outcome_code, "1")
        self.assertEqual(options[("winner", "ничья")].outcome_code, "X")
        self.assertEqual(options[("handicap", "1 (-1.5)")].outcome_code, "home -1.5")
        self.assertNotIn(("handicap", "something odd"), options)

    def test_basketball_draw_is_not_bettable(self):
        match = self._match("basketball")
        MatchOdds.objects.create(match=match, home_win_bet=1.5, x_bet=12.0, away_win_bet=2.6, d_1x=1.4)

        options = match_bet_options(match)
        buttons = {
            button["outcome_code"]: button["bettable"]
            for tab in build_match_odds_tabs(match)
            for section in tab["sections"]
            for row in section["rows"]
            for button in row["odds"]
        }

        self.assertIn(("winner", "хозяева"), options)
        self.assertNotIn(("winner", "ничья"), options)
        self.assertFalse(buttons["X"])
        self.assertFalse(buttons["1X"])


class SettlementWithRegularTimeTests(TestCase):
    def setUp(self):
        self.analyst = User.objects.create_user(
            username="codes-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.hockey = Sport.objects.create(external_id=3, code="hockey", name="Hockey")

    def _coupon(self, match, market, selection, outcome_code):
        coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("100"),
            possible_payout=Decimal("200"),
            published_at=timezone.now() - timedelta(hours=4),
        )
        prediction = Prediction.objects.create(
            coupon=coupon,
            match=match,
            market=market,
            selection=selection,
            outcome_code=outcome_code,
            coefficient=Decimal("2.00"),
            stake=Decimal("100"),
        )
        return coupon, prediction

    def _hockey_match(self, external_id, score, periods):
        return Match.objects.create(
            external_id=external_id,
            sport=self.hockey,
            sync_scope=Match.SyncScope.FINISHED,
            starts_at=timezone.now() - timedelta(hours=3),
            score=score,
            raw_data={"periods": periods},
        )

    def test_hockey_is_settled_by_regular_time(self):
        # Real payload shape: 4:4 after regulation, shootout won 4:3, final score 5:4.
        match = self._hockey_match(
            776001,
            "5-4",
            {"first": "0-2", "second": "3-1", "third": "1-1", "overtime": "0-0", "penalties": "4-3"},
        )
        _, draw = self._coupon(match, "winner", "Ничья", "X")
        _, under = self._coupon(match, "total", "ТМ 8.5", "under 8.5")

        settle_finished_matches()

        draw.refresh_from_db()
        under.refresh_from_db()
        self.assertEqual(draw.state_status, Prediction.StateStatus.WIN)
        self.assertEqual(under.state_status, Prediction.StateStatus.WIN)

    def test_hockey_without_periods_and_one_goal_margin_goes_to_review(self):
        match = self._hockey_match(776002, "3-2", {"items": [], "available": False})
        _, prediction = self._coupon(match, "winner", "Хозяева", "1")

        settle_finished_matches()

        prediction.refresh_from_db()
        self.assertEqual(prediction.state_status, "")
        self.assertTrue(
            MatchManualReview.objects.filter(
                match=match,
                reason=MatchManualReview.Reason.REGULAR_TIME_UNKNOWN,
            ).exists()
        )

    def test_admin_regular_time_score_resolves_ambiguous_hockey_match(self):
        match = self._hockey_match(776004, "3-2", {"items": [], "available": False})
        _, prediction = self._coupon(match, "winner", "Ничья", "X")
        settle_finished_matches()

        Match.objects.filter(pk=match.pk).update(regular_time_score="2-2")
        settle_finished_matches()

        prediction.refresh_from_db()
        self.assertEqual(prediction.state_status, Prediction.StateStatus.WIN)
        self.assertFalse(
            MatchManualReview.objects.filter(
                match=match,
                reason=MatchManualReview.Reason.REGULAR_TIME_UNKNOWN,
                status=MatchManualReview.Status.OPEN,
            ).exists()
        )

    def test_ambiguous_hockey_match_without_predictions_is_not_flagged(self):
        match = self._hockey_match(776005, "3-2", {"items": [], "available": False})

        settle_finished_matches()

        self.assertFalse(MatchManualReview.objects.filter(match=match).exists())

    def test_hockey_without_periods_and_clear_margin_is_settled(self):
        match = self._hockey_match(776003, "4-1", {"items": [], "available": False})
        _, prediction = self._coupon(match, "winner", "Хозяева", "1")

        settle_finished_matches()

        prediction.refresh_from_db()
        self.assertEqual(prediction.state_status, Prediction.StateStatus.WIN)


class CouponStoresOutcomeCodeTests(TestCase):
    def test_published_prediction_has_outcome_code(self):
        analyst = User.objects.create_user(
            username="code-store-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        match = Match.objects.create(
            external_id=777001,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now() + timedelta(hours=2),
            raw_data={"teams": {"home": {"name": {"ru": "Арсенал"}}, "away": {"name": {"ru": "Челси"}}}},
        )
        MatchOdds.objects.create(match=match, away_win_bet=4.1, handicaps_all={"Away +1.5": 1.9})
        self.client.force_login(analyst)

        response = self.client.post(
            reverse("game:create_coupon"),
            data=json.dumps(
                {
                    "stake": "100",
                    "confidence": 70,
                    "items": [
                        {"match_id": match.id, "market": "handicap", "selection": "Away +1.5", "coefficient": "1.90"},
                    ],
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(Prediction.objects.get(coupon__author=analyst).outcome_code, "away +1.5")
