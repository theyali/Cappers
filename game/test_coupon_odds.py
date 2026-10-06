import json
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from django.urls import resolve, reverse
from django.utils import timezone

from cabinet.models import User
from game import views
from game.models import Match, MatchOdds, Prediction, PredictionCoupon
from game.services.bet_options import build_match_odds_tabs, match_bet_options
from game.services.coupon_validation import parse_stake
from wallets.models import CoinTransaction


def _raw_match_data(home: str, away: str) -> dict:
    return {
        "teams": {
            "home": {"name": {"ru": home}},
            "away": {"name": {"ru": away}},
        },
        "league": {"name": {"ru": "Лига"}},
    }


class CouponStakeParsingTests(SimpleTestCase):
    def test_coupon_route_uses_view_directly(self):
        match = resolve(reverse("game:create_coupon"))
        self.assertIs(match.func, views.create_coupon)

    def test_minimum_stake_is_enforced_for_publish(self):
        with self.assertRaisesMessage(ValidationError, "Минимальная сумма прогноза — 100 коинов."):
            parse_stake("99", required=True)

    def test_maximum_stake_is_enforced_for_publish(self):
        with self.assertRaisesMessage(ValidationError, "Максимальная сумма прогноза — 1 000 000 коинов."):
            parse_stake("1000001", required=True)

    def test_fractional_stake_is_rejected_for_publish(self):
        with self.assertRaisesMessage(ValidationError, "целым числом коинов"):
            parse_stake("100.5", required=True)

    def test_draft_autosave_keeps_partial_stake_while_user_is_typing(self):
        self.assertEqual(parse_stake("9", required=False), Decimal("9"))

    def test_draft_autosave_ignores_invalid_or_huge_stake(self):
        self.assertEqual(parse_stake("abc", required=False), Decimal("0"))
        self.assertEqual(parse_stake("1e30", required=False), Decimal("0"))
        self.assertEqual(parse_stake("NaN", required=False), Decimal("0"))


class CouponOddsValidationTests(TestCase):
    def setUp(self):
        self.analyst = User.objects.create_user(
            username="odds-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.match = self._match(771001, "Арсенал", "Челси")
        MatchOdds.objects.create(
            match=self.match,
            home_win_bet=1.85,
            x_bet=3.40,
            away_win_bet=4.10,
            team_totals_all={"Home Over 1.5": 2.10},
            exact_score_all={"5:5": 1500},
        )
        self.client.force_login(self.analyst)

    def _match(self, external_id, home, away):
        return Match.objects.create(
            external_id=external_id,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now() + timedelta(hours=2),
            raw_data=_raw_match_data(home, away),
        )

    def _item(self, match=None, market="winner", selection="Арсенал", coefficient="1.85"):
        return {
            "match_id": (match or self.match).id,
            "market": market,
            "selection": selection,
            "coefficient": coefficient,
        }

    def _post(self, items, *, stake="100", autosave=False):
        return self.client.post(
            reverse("game:create_coupon"),
            data=json.dumps(
                {
                    "stake": stake,
                    "confidence": 70,
                    "autosave": autosave,
                    "items": items,
                }
            ),
            content_type="application/json",
        )

    def test_publish_uses_coefficient_from_line(self):
        response = self._post([self._item()])

        self.assertEqual(response.status_code, 200, response.content)
        prediction = Prediction.objects.get(coupon__author=self.analyst)
        self.assertEqual(prediction.coefficient, Decimal("1.85"))
        self.assertEqual(prediction.selection, "Арсенал")
        self.assertEqual(prediction.coupon.possible_payout, Decimal("185.00"))

    def test_publish_with_tampered_coefficient_is_rejected_with_current_odds(self):
        response = self._post([self._item(coefficient="50")])

        self.assertEqual(response.status_code, 409)
        data = response.json()
        self.assertIn("Коэффициенты изменились", data["error"])
        self.assertEqual(
            data["odds_changed"],
            [
                {
                    "match_id": self.match.id,
                    "market": "winner",
                    "selection": "Арсенал",
                    "coefficient": "1.85",
                    "previous": "50.00",
                }
            ],
        )
        self.assertFalse(
            PredictionCoupon.objects.filter(
                author=self.analyst,
                published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            ).exists()
        )
        self.assertFalse(
            CoinTransaction.objects.filter(
                user=self.analyst,
                kind=CoinTransaction.Kind.PREDICTION_STAKE,
            ).exists()
        )

    def test_publish_without_coefficient_asks_to_confirm_current_odds(self):
        response = self._post([self._item(coefficient="")])

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["odds_changed"][0]["coefficient"], "1.85")

    def test_autosave_stores_coefficient_from_line(self):
        response = self._post([self._item(coefficient="50")], autosave=True)

        self.assertEqual(response.status_code, 200, response.content)
        draft = response.json()["draft"]
        self.assertEqual(draft["items"][0]["coefficient"], "1.85")
        prediction = Prediction.objects.get(coupon__author=self.analyst)
        self.assertEqual(prediction.coefficient, Decimal("1.85"))

    def test_selection_is_matched_case_and_space_insensitive(self):
        response = self._post([self._item(selection="  арсенал ")])

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(Prediction.objects.get(coupon__author=self.analyst).selection, "Арсенал")

    def test_outcome_that_is_not_offered_is_rejected(self):
        response = self._post([self._item(selection="Барселона")])

        self.assertEqual(response.status_code, 400)
        self.assertIn("сейчас недоступен", response.json()["error"])
        self.assertFalse(PredictionCoupon.objects.filter(author=self.analyst).exists())

    def test_market_without_automatic_settlement_is_rejected(self):
        response = self._post(
            [self._item(market="team_total", selection="Home Over 1.5", coefficient="2.10")]
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("сейчас недоступен", response.json()["error"])

    def test_match_without_line_is_rejected(self):
        match = self._match(771002, "Ливерпуль", "Эвертон")

        response = self._post([self._item(match=match, selection="Ливерпуль")])

        self.assertEqual(response.status_code, 400)
        self.assertIn("сейчас недоступен", response.json()["error"])

    def test_coefficient_one_from_line_is_rejected(self):
        MatchOdds.objects.filter(match=self.match).update(home_win_bet=1.00)

        response = self._post([self._item(coefficient="1.00")])

        self.assertEqual(response.status_code, 400)
        self.assertIn("Коэффициент 1.00", response.json()["error"])

    def test_coefficient_above_limit_is_rejected(self):
        response = self._post(
            [self._item(market="exact_score", selection="5:5", coefficient="1500.00")]
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Коэффициент выше 1 000", response.json()["error"])

    def test_total_coefficient_above_limit_is_rejected(self):
        items = []
        for index in range(3):
            match = self._match(771100 + index, f"Хозяева {index}", f"Гости {index}")
            MatchOdds.objects.create(match=match, home_win_bet=30)
            items.append(self._item(match=match, selection=f"Хозяева {index}", coefficient="30.00"))

        response = self._post(items)

        self.assertEqual(response.status_code, 400)
        self.assertIn("Общий коэффициент прогноза", response.json()["error"])


class BetOptionsTests(TestCase):
    def setUp(self):
        self.match = Match.objects.create(
            external_id=772001,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now() + timedelta(hours=2),
            raw_data=_raw_match_data("Арсенал", "Челси"),
        )

    def _buttons(self):
        return [
            button
            for tab in build_match_odds_tabs(self.match)
            for section in tab["sections"]
            for row in section["rows"]
            for button in row["odds"]
        ]

    def test_only_settleable_markets_are_bettable_on_match_page(self):
        MatchOdds.objects.create(
            match=self.match,
            home_win_bet=1.85,
            team_totals_all={"Home Over 1.5": 2.10},
        )

        bettable = {button["market"]: button["bettable"] for button in self._buttons()}

        self.assertTrue(bettable["winner"])
        self.assertFalse(bettable["team_total"])
        self.assertNotIn(("team_total", "home over 1.5"), match_bet_options(self.match))

    def test_saved_prediction_coefficients_are_not_bettable_without_line(self):
        analyst = User.objects.create_user(
            username="saved-odds-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        coupon = PredictionCoupon.objects.create(
            author=analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("185.00"),
            published_at=timezone.now(),
        )
        Prediction.objects.create(
            coupon=coupon,
            match=self.match,
            market="winner",
            selection="Арсенал",
            coefficient=Decimal("1.85"),
            stake=Decimal("100.00"),
        )

        buttons = self._buttons()

        self.assertEqual(len(buttons), 1)
        self.assertFalse(buttons[0]["bettable"])
        self.assertEqual(match_bet_options(self.match), {})
