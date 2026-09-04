import json
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.urls import resolve, reverse
from django.utils import timezone

from cabinet.models import User
from game.models import Match, MatchOdds, Prediction, PredictionCoupon, Sport
from tournaments import views
from tournaments.services.coupons import create_tournament_coupon
from tournaments.services.join import TournamentJoinError, join_tournament
from tournaments.services.leaderboard import finalize_tournament_results, tournament_leaderboard
from tournaments.services.rules import TournamentRuleError, validate_tournament_coupon

from .models import (
    Tournament,
    TournamentCoupon,
    TournamentParticipant,
    TournamentPredictionEntry,
)


TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


class TournamentPredictionEntryTests(TestCase):
    def setUp(self):
        self.analyst = User.objects.create_user(
            username="tournament-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.tournament = Tournament.objects.create(
            title="September Profit Cup",
            status=Tournament.Status.PUBLISHED,
            starts_at=timezone.now() - timedelta(hours=1),
            ends_at=timezone.now() + timedelta(days=7),
            prize_first=Decimal("1000.00"),
            prize_second=Decimal("500.00"),
            prize_third=Decimal("250.00"),
        )
        self.participant = TournamentParticipant.objects.create(
            tournament=self.tournament,
            user=self.analyst,
        )
        self.match = Match.objects.create(
            external_id=770001,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now() + timedelta(hours=3),
        )

    def _tournament_prediction_entry(self, selection: str) -> TournamentPredictionEntry:
        coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("200.00"),
            confidence=80,
            published_at=timezone.now(),
        )
        prediction = Prediction.objects.create(
            coupon=coupon,
            match=self.match,
            market="winner",
            selection=selection,
            coefficient=Decimal("2.00"),
            stake=Decimal("100.00"),
        )
        tournament_coupon = TournamentCoupon.objects.create(
            tournament=self.tournament,
            participant=self.participant,
            coupon=coupon,
        )
        return TournamentPredictionEntry.objects.create(
            tournament=self.tournament,
            participant=self.participant,
            tournament_coupon=tournament_coupon,
            prediction=prediction,
            match=self.match,
        )

    def test_participant_can_use_match_only_once_per_tournament(self):
        self._tournament_prediction_entry("Хозяева")

        with self.assertRaises(IntegrityError):
            self._tournament_prediction_entry("Гости")


class TournamentServiceTests(TestCase):
    def setUp(self):
        self.football = Sport.objects.create(
            external_id=1001,
            code="football",
            name="Football",
            name_ru="Футбол",
        )
        self.basketball = Sport.objects.create(
            external_id=1002,
            code="basketball",
            name="Basketball",
            name_ru="Баскетбол",
        )
        self.analyst = User.objects.create_user(
            username="rules-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.reader = User.objects.create_user(
            username="rules-reader",
            password="safe-test-password",
            role=User.Role.READER,
        )
        self.tournament = Tournament.objects.create(
            title="Rules Cup",
            status=Tournament.Status.PUBLISHED,
            starts_at=timezone.now() - timedelta(hours=1),
            ends_at=timezone.now() + timedelta(days=3),
            prize_first=Decimal("1000.00"),
            prize_second=Decimal("500.00"),
            prize_third=Decimal("250.00"),
            min_coefficient=Decimal("2.00"),
            min_confidence=90,
            coupon_type_rule=Tournament.CouponTypeRule.SINGLE,
        )
        self.tournament.allowed_sports.add(self.football)
        self.participant = TournamentParticipant.objects.create(
            tournament=self.tournament,
            user=self.analyst,
        )
        self.football_match = Match.objects.create(
            external_id=880001,
            sport=self.football,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now() + timedelta(hours=3),
        )
        self.basketball_match = Match.objects.create(
            external_id=880002,
            sport=self.basketball,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now() + timedelta(hours=4),
        )

    def _item(self, match=None, coefficient=Decimal("2.00")):
        return {
            "match": match or self.football_match,
            "market": "winner",
            "selection": "Хозяева",
            "coefficient": coefficient,
        }

    def _payload(self, match=None, coefficient="2.00", confidence=95, stake="100"):
        match = match or self.football_match
        return {
            "stake": stake,
            "confidence": confidence,
            "items": [
                {
                    "match_id": match.id,
                    "market": "winner",
                    "selection": "Хозяева",
                    "coefficient": coefficient,
                }
            ],
        }

    def test_join_tournament_allows_only_analysts(self):
        with self.assertRaises(TournamentJoinError):
            join_tournament(self.reader, self.tournament)

        participant = join_tournament(self.analyst, self.tournament)

        self.assertEqual(participant.status, TournamentParticipant.Status.ACTIVE)

    def test_rules_validate_min_coefficient_confidence_sport_and_type(self):
        with self.assertRaisesMessage(TournamentRuleError, "Минимальная уверенность"):
            validate_tournament_coupon(
                self.tournament,
                self.participant,
                confidence=80,
                items=[self._item()],
            )

        with self.assertRaisesMessage(TournamentRuleError, "Минимальный коэффициент"):
            validate_tournament_coupon(
                self.tournament,
                self.participant,
                confidence=95,
                items=[self._item(coefficient=Decimal("1.90"))],
            )

        with self.assertRaisesMessage(TournamentRuleError, "Баскетбол"):
            validate_tournament_coupon(
                self.tournament,
                self.participant,
                confidence=95,
                items=[self._item(match=self.basketball_match)],
            )

        with self.assertRaisesMessage(TournamentRuleError, "только одиночные"):
            validate_tournament_coupon(
                self.tournament,
                self.participant,
                confidence=95,
                items=[self._item(), self._item(match=self.basketball_match)],
            )

    def test_create_tournament_coupon_creates_public_coupon_and_tournament_links(self):
        coupon, tournament_coupon = create_tournament_coupon(
            user=self.analyst,
            tournament=self.tournament,
            payload=self._payload(),
        )

        self.assertEqual(coupon.published_status, PredictionCoupon.PublishedStatus.PUBLISHED)
        self.assertEqual(coupon.coupon_type, PredictionCoupon.CouponType.SINGLE)
        self.assertEqual(coupon.audience, PredictionCoupon.Audience.FREE)
        self.assertEqual(tournament_coupon.tournament, self.tournament)
        self.assertEqual(tournament_coupon.participant, self.participant)
        self.assertEqual(TournamentPredictionEntry.objects.filter(tournament=self.tournament).count(), 1)
        self.analyst.capper_balance.refresh_from_db()
        self.assertEqual(self.analyst.capper_balance.balance, Decimal("9900.00"))

    def test_create_tournament_coupon_rejects_second_prediction_for_same_match(self):
        create_tournament_coupon(
            user=self.analyst,
            tournament=self.tournament,
            payload=self._payload(),
        )

        with self.assertRaisesMessage(ValidationError, "один матч"):
            create_tournament_coupon(
                user=self.analyst,
                tournament=self.tournament,
                payload=self._payload(match=self.football_match),
            )

    def test_leaderboard_and_finalization_calculate_places(self):
        second = User.objects.create_user(
            username="second-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        second_participant = TournamentParticipant.objects.create(
            tournament=self.tournament,
            user=second,
        )
        first_coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=PredictionCoupon.StateStatus.WIN,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("300.00"),
            confidence=95,
            published_at=timezone.now(),
        )
        second_coupon = PredictionCoupon.objects.create(
            author=second,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=PredictionCoupon.StateStatus.LOSE,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("250.00"),
            confidence=95,
            published_at=timezone.now(),
        )
        TournamentCoupon.objects.create(
            tournament=self.tournament,
            participant=self.participant,
            coupon=first_coupon,
        )
        TournamentCoupon.objects.create(
            tournament=self.tournament,
            participant=second_participant,
            coupon=second_coupon,
        )

        rows = tournament_leaderboard(self.tournament)

        self.assertEqual(rows[0]["participant"], self.participant)
        self.assertEqual(rows[0]["profit"], Decimal("200.00"))
        self.assertEqual(rows[0]["roi_percent"], Decimal("200.00"))
        self.assertEqual(rows[1]["participant"], second_participant)
        self.assertEqual(rows[1]["profit"], Decimal("-100.00"))

        self.tournament.ends_at = timezone.now() - timedelta(minutes=1)
        self.tournament.save(update_fields=("ends_at", "updated_at"))
        results = finalize_tournament_results(self.tournament)

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].participant, self.participant)
        self.assertEqual(results[0].rank, 1)
        self.assertEqual(results[0].prize_amount, Decimal("1000.00"))


class TournamentCouponEndpointTests(TestCase):
    def setUp(self):
        self.analyst = User.objects.create_user(
            username="endpoint-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.reader = User.objects.create_user(
            username="endpoint-reader",
            password="safe-test-password",
            role=User.Role.READER,
        )
        self.tournament = Tournament.objects.create(
            title="Endpoint Cup",
            status=Tournament.Status.PUBLISHED,
            starts_at=timezone.now() - timedelta(hours=1),
            ends_at=timezone.now() + timedelta(days=3),
            min_coefficient=Decimal("1.50"),
            min_confidence=70,
        )
        self.participant = TournamentParticipant.objects.create(
            tournament=self.tournament,
            user=self.analyst,
        )
        self.match = Match.objects.create(
            external_id=990001,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now() + timedelta(hours=3),
        )

    def _payload(self):
        return {
            "stake": "200",
            "confidence": 75,
            "items": [
                {
                    "match_id": self.match.id,
                    "market": "winner",
                    "selection": "Хозяева",
                    "coefficient": "1.80",
                }
            ],
        }

    def test_create_coupon_route_uses_tournament_view(self):
        match = resolve(
            reverse("tournaments:create_coupon", kwargs={"slug": self.tournament.slug})
        )

        self.assertIs(match.func, views.create_coupon)

    def test_endpoint_creates_public_coupon_and_returns_balance(self):
        self.client.force_login(self.analyst)

        response = self.client.post(
            reverse("tournaments:create_coupon", kwargs={"slug": self.tournament.slug}),
            data=json.dumps(self._payload()),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["message"], "Прогноз турнира опубликован.")
        self.assertEqual(payload["balance"], "9800.00")
        self.assertEqual(PredictionCoupon.objects.count(), 1)
        coupon = PredictionCoupon.objects.get()
        self.assertEqual(coupon.tournament_link.tournament, self.tournament)
        self.assertEqual(coupon.predictions.count(), 1)

    def test_endpoint_rejects_user_without_participation(self):
        other = User.objects.create_user(
            username="outside-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.client.force_login(other)

        response = self.client.post(
            reverse("tournaments:create_coupon", kwargs={"slug": self.tournament.slug}),
            data=json.dumps(self._payload()),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Подключитесь к турниру", response.json()["error"])
        self.assertFalse(PredictionCoupon.objects.exists())

    def test_endpoint_rejects_reader(self):
        self.client.force_login(self.reader)

        response = self.client.post(
            reverse("tournaments:create_coupon", kwargs={"slug": self.tournament.slug}),
            data=json.dumps(self._payload()),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn("капперы", response.json()["error"])

    def test_endpoint_rejects_invalid_json(self):
        self.client.force_login(self.analyst)

        response = self.client.post(
            reverse("tournaments:create_coupon", kwargs={"slug": self.tournament.slug}),
            data="{bad json",
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "Некорректный JSON.")


@override_settings(STORAGES=TEST_STORAGES)
class TournamentPageTests(TestCase):
    def setUp(self):
        self.analyst = User.objects.create_user(
            username="page-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.tournament = Tournament.objects.create(
            title="Page Cup",
            status=Tournament.Status.PUBLISHED,
            starts_at=timezone.now() - timedelta(hours=1),
            ends_at=timezone.now() + timedelta(days=3),
            prize_first=Decimal("1000.00"),
            prize_second=Decimal("500.00"),
            prize_third=Decimal("250.00"),
        )
        self.match = Match.objects.create(
            external_id=991001,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now() + timedelta(hours=4),
        )
        MatchOdds.objects.create(
            match=self.match,
            home_win_bet=2.2,
            x_bet=3.1,
            away_win_bet=2.8,
        )

    def _predict_url(self):
        selected_date = timezone.localtime(self.match.starts_at).date().isoformat()
        return (
            reverse("tournaments:predict", kwargs={"slug": self.tournament.slug})
            + f"?date={selected_date}"
        )

    def test_index_lists_published_tournament_cards(self):
        Tournament.objects.create(
            title="Hidden Cup",
            status=Tournament.Status.DRAFT,
            starts_at=timezone.now(),
            ends_at=timezone.now() + timedelta(days=1),
        )

        response = self.client.get(reverse("tournaments:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Page Cup")
        self.assertContains(response, "Открыть турнир")
        self.assertNotContains(response, "Hidden Cup")

    def test_detail_shows_tournament_state_and_join_action_for_analyst(self):
        self.client.force_login(self.analyst)

        response = self.client.get(
            reverse("tournaments:detail", kwargs={"slug": self.tournament.slug})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Page Cup")
        self.assertContains(response, "Подключиться")
        self.assertContains(response, "Таблица турнира")
        self.assertContains(response, "Прогнозы турнира")

    def test_detail_links_joined_participant_to_tournament_prediction_page(self):
        TournamentParticipant.objects.create(
            tournament=self.tournament,
            user=self.analyst,
        )
        self.client.force_login(self.analyst)

        response = self.client.get(
            reverse("tournaments:detail", kwargs={"slug": self.tournament.slug})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            reverse("tournaments:predict", kwargs={"slug": self.tournament.slug}),
        )
        self.assertContains(response, "Сделать прогноз")

    def test_predict_redirects_without_active_participation(self):
        self.client.force_login(self.analyst)

        response = self.client.get(self._predict_url())

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.tournament.get_absolute_url())

    def test_predict_redirects_when_tournament_is_not_live(self):
        self.tournament.starts_at = timezone.now() + timedelta(days=1)
        self.tournament.ends_at = timezone.now() + timedelta(days=2)
        self.tournament.save(update_fields=("starts_at", "ends_at", "updated_at"))
        TournamentParticipant.objects.create(
            tournament=self.tournament,
            user=self.analyst,
        )
        self.client.force_login(self.analyst)

        response = self.client.get(self._predict_url())

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.tournament.get_absolute_url())

    def test_predict_page_reuses_match_list_and_coupon_for_active_participant(self):
        TournamentParticipant.objects.create(
            tournament=self.tournament,
            user=self.analyst,
        )
        self.client.force_login(self.analyst)

        response = self.client.get(self._predict_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Page Cup: прогноз")
        self.assertContains(
            response,
            f'data-create-url="{reverse("tournaments:create_coupon", kwargs={"slug": self.tournament.slug})}"',
        )
        self.assertContains(response, 'data-autosave="false"')
        self.assertContains(response, 'data-bet-option data-bet-key="winner-home"')

    def test_predict_page_locks_match_already_used_in_tournament(self):
        participant = TournamentParticipant.objects.create(
            tournament=self.tournament,
            user=self.analyst,
        )
        coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("220.00"),
            confidence=80,
            published_at=timezone.now(),
        )
        prediction = Prediction.objects.create(
            coupon=coupon,
            match=self.match,
            market="winner",
            selection="Хозяева",
            coefficient=Decimal("2.20"),
            stake=Decimal("100.00"),
        )
        tournament_coupon = TournamentCoupon.objects.create(
            tournament=self.tournament,
            participant=participant,
            coupon=coupon,
        )
        TournamentPredictionEntry.objects.create(
            tournament=self.tournament,
            participant=participant,
            tournament_coupon=tournament_coupon,
            prediction=prediction,
            match=self.match,
        )
        self.client.force_login(self.analyst)

        response = self.client.get(self._predict_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Матч уже использован в турнире")
        self.assertNotContains(response, 'data-bet-option data-bet-key="winner-home"')

    def test_join_view_adds_active_participant(self):
        self.client.force_login(self.analyst)

        response = self.client.post(
            reverse("tournaments:join", kwargs={"slug": self.tournament.slug}),
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            TournamentParticipant.objects.filter(
                tournament=self.tournament,
                user=self.analyst,
                status=TournamentParticipant.Status.ACTIVE,
            ).exists()
        )

    def test_detail_shows_tournament_predictions(self):
        participant = TournamentParticipant.objects.create(
            tournament=self.tournament,
            user=self.analyst,
        )
        coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=PredictionCoupon.StateStatus.PENDING,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("220.00"),
            confidence=80,
            published_at=timezone.now(),
        )
        prediction = Prediction.objects.create(
            coupon=coupon,
            match=self.match,
            market="winner",
            selection="Хозяева",
            coefficient=Decimal("2.20"),
            stake=Decimal("100.00"),
        )
        tournament_coupon = TournamentCoupon.objects.create(
            tournament=self.tournament,
            participant=participant,
            coupon=coupon,
        )
        TournamentPredictionEntry.objects.create(
            tournament=self.tournament,
            participant=participant,
            tournament_coupon=tournament_coupon,
            prediction=prediction,
            match=self.match,
        )

        response = self.client.get(
            reverse("tournaments:detail", kwargs={"slug": self.tournament.slug})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Хозяева")
        self.assertContains(response, "page-capper")
        self.assertContains(response, 'data-prediction-card="')
