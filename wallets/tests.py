import json
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cabinet.models import AnalystProfile, User
from game.models import Match, Prediction, PredictionCoupon, Sport
from game.services.settlement import settle_coupon
from cabinet.paid_predictions import subscribe_to_paid_predictions
from tournaments.models import Tournament, TournamentCoupon, TournamentParticipant
from wallets.models import BalanceTransaction, CopiedBet, CopyBettingSubscription, RealBalanceTransaction
from wallets.services import (
    activate_copybetting,
    approve_real_withdrawal,
    cancel_real_withdrawal,
    charge_prediction_stake,
    copy_published_coupon,
    pause_copybetting,
    request_real_withdrawal,
    resume_copybetting,
    stop_copybetting,
)


TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


class CapperBalanceTests(TestCase):
    def setUp(self):
        self.analyst = User.objects.create_user(
            username="balance-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.match = Match.objects.create(
            external_id=881001,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now() + timedelta(hours=1),
            raw_data={
                "teams": {
                    "home": {"name": {"ru": "Хозяева"}},
                    "away": {"name": {"ru": "Гости"}},
                },
                "league": {"name": {"ru": "Лига"}},
            },
        )

    def _payload(self, stake="500"):
        return {
            "stake": stake,
            "confidence": 70,
            "items": [
                {
                    "match_id": self.match.id,
                    "market": "winner",
                    "selection": "Хозяева",
                    "coefficient": "1.70",
                }
            ],
        }

    def test_new_analyst_gets_starting_virtual_balance(self):
        self.analyst.capper_balance.refresh_from_db()

        self.assertEqual(self.analyst.capper_balance.balance, Decimal("10000.00"))
        self.assertTrue(
            BalanceTransaction.objects.filter(
                user=self.analyst,
                kind=BalanceTransaction.Kind.INITIAL_BONUS,
                amount=Decimal("10000.00"),
            ).exists()
        )

    def test_new_reader_gets_same_virtual_balance(self):
        reader = User.objects.create_user(
            username="balance-reader",
            password="safe-test-password",
            role=User.Role.READER,
        )

        reader.capper_balance.refresh_from_db()
        self.assertEqual(reader.capper_balance.balance, Decimal("10000.00"))
        self.assertTrue(
            BalanceTransaction.objects.filter(
                user=reader,
                kind=BalanceTransaction.Kind.INITIAL_BONUS,
                amount=Decimal("10000.00"),
            ).exists()
        )

    def test_publishing_coupon_charges_stake(self):
        self.client.force_login(self.analyst)

        response = self.client.post(
            reverse("game:create_coupon"),
            data=json.dumps(self._payload("500")),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["balance"], "9500.00")
        self.assertEqual(response.json()["balance_display"], "9 500")
        self.analyst.capper_balance.refresh_from_db()
        self.assertEqual(self.analyst.capper_balance.balance, Decimal("9500.00"))
        self.assertTrue(
            BalanceTransaction.objects.filter(
                user=self.analyst,
                kind=BalanceTransaction.Kind.PREDICTION_STAKE,
                amount=Decimal("-500.00"),
            ).exists()
        )

    def test_coupon_is_not_created_when_balance_is_too_low(self):
        self.analyst.capper_balance.balance = Decimal("50.00")
        self.analyst.capper_balance.save(update_fields=["balance", "updated_at"])
        self.client.force_login(self.analyst)

        response = self.client.post(
            reverse("game:create_coupon"),
            data=json.dumps(self._payload("500")),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 402)
        self.assertIn("Недостаточно средств", response.json()["error"])
        self.assertFalse(PredictionCoupon.objects.filter(author=self.analyst).exists())
        self.analyst.capper_balance.refresh_from_db()
        self.assertEqual(self.analyst.capper_balance.balance, Decimal("50.00"))

    def test_settled_winning_coupon_credits_payout_once(self):
        coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("250.00"),
            confidence=80,
            published_at=timezone.now(),
        )
        Prediction.objects.create(
            coupon=coupon,
            match=self.match,
            market="winner",
            selection="Хозяева",
            coefficient=Decimal("2.50"),
            stake=Decimal("100.00"),
            state_status=Prediction.StateStatus.WIN,
        )
        charge_prediction_stake(self.analyst, coupon, coupon.total_stake)

        settle_coupon(coupon.id)
        settle_coupon(coupon.id)

        self.analyst.capper_balance.refresh_from_db()
        self.assertEqual(self.analyst.capper_balance.balance, Decimal("10150.00"))
        self.assertEqual(
            BalanceTransaction.objects.filter(
                user=self.analyst,
                kind=BalanceTransaction.Kind.PREDICTION_PAYOUT,
                related_id=coupon.id,
            ).count(),
            1,
        )

    def test_settled_winning_coupon_recovers_missing_stake_transaction(self):
        coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("250.00"),
            confidence=80,
            published_at=timezone.now(),
        )
        Prediction.objects.create(
            coupon=coupon,
            match=self.match,
            market="winner",
            selection="Хозяева",
            coefficient=Decimal("2.50"),
            stake=Decimal("100.00"),
            state_status=Prediction.StateStatus.WIN,
        )

        settle_coupon(coupon.id)
        settle_coupon(coupon.id)

        self.analyst.capper_balance.refresh_from_db()
        self.assertEqual(self.analyst.capper_balance.balance, Decimal("10150.00"))
        self.assertEqual(
            BalanceTransaction.objects.filter(
                user=self.analyst,
                kind=BalanceTransaction.Kind.PREDICTION_STAKE,
                related_id=coupon.id,
            ).count(),
            1,
        )
        self.assertEqual(
            BalanceTransaction.objects.filter(
                user=self.analyst,
                kind=BalanceTransaction.Kind.PREDICTION_PAYOUT,
                related_id=coupon.id,
            ).count(),
            1,
        )

    def test_top_up_view_adds_virtual_money_and_redirects_back(self):
        self.client.force_login(self.analyst)

        response = self.client.post(
            reverse("wallets:top_up"),
            data={"next": reverse("cabinet:profile")},
        )

        self.assertEqual(response.status_code, 302)
        self.analyst.capper_balance.refresh_from_db()
        self.assertEqual(self.analyst.capper_balance.balance, Decimal("20000.00"))
        self.assertTrue(
            BalanceTransaction.objects.filter(
                user=self.analyst,
                kind=BalanceTransaction.Kind.VIRTUAL_DEPOSIT,
                amount=Decimal("10000.00"),
            ).exists()
        )

    def test_reader_can_top_up_virtual_balance(self):
        reader = User.objects.create_user(
            username="top-up-reader",
            password="safe-test-password",
            role=User.Role.READER,
        )
        self.client.force_login(reader)

        response = self.client.post(reverse("wallets:top_up"))

        self.assertEqual(response.status_code, 302)
        reader.capper_balance.refresh_from_db()
        self.assertEqual(reader.capper_balance.balance, Decimal("20000.00"))

    def test_copybetting_copies_published_coupon_and_charges_reader(self):
        reader = User.objects.create_user(
            username="copy-reader",
            password="safe-test-password",
            role=User.Role.READER,
        )
        subscription = activate_copybetting(
            user=reader,
            analyst=self.analyst,
            bank_amount=Decimal("1000.00"),
            stake_percent=Decimal("10.00"),
            stop_loss_amount=Decimal("300.00"),
        )
        coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("500.00"),
            possible_payout=Decimal("1000.00"),
            confidence=80,
            published_at=timezone.now(),
        )

        copied = copy_published_coupon(coupon)

        self.assertEqual(len(copied), 1)
        copied_bet = copied[0]
        self.assertEqual(copied_bet.subscription, subscription)
        self.assertEqual(copied_bet.stake, Decimal("100.00"))
        self.assertEqual(copied_bet.possible_payout, Decimal("200.00"))
        reader.capper_balance.refresh_from_db()
        self.assertEqual(reader.capper_balance.balance, Decimal("9900.00"))
        self.assertTrue(
            BalanceTransaction.objects.filter(
                user=reader,
                kind=BalanceTransaction.Kind.COPYBET_STAKE,
                amount=Decimal("-100.00"),
            ).exists()
        )

    def test_activating_copybetting_does_not_copy_existing_pending_coupon(self):
        old_coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("500.00"),
            possible_payout=Decimal("1000.00"),
            confidence=80,
            published_at=timezone.now(),
        )
        reader = User.objects.create_user(
            username="copy-existing-reader",
            password="safe-test-password",
            role=User.Role.READER,
        )

        subscription = activate_copybetting(
            user=reader,
            analyst=self.analyst,
            bank_amount=Decimal("1000.00"),
            stake_percent=Decimal("10.00"),
        )
        new_coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("500.00"),
            possible_payout=Decimal("1000.00"),
            confidence=80,
            published_at=timezone.now(),
        )
        copied = copy_published_coupon(new_coupon)

        self.assertFalse(CopiedBet.objects.filter(user=reader, source_coupon=old_coupon).exists())
        self.assertEqual(len(copied), 1)
        copied_bet = CopiedBet.objects.get(user=reader, source_coupon=new_coupon)
        self.assertEqual(copied_bet.subscription, subscription)
        self.assertEqual(copied_bet.stake, Decimal("100.00"))
        self.assertEqual(copied_bet.state_status, CopiedBet.StateStatus.PENDING)
        reader.capper_balance.refresh_from_db()
        self.assertEqual(reader.capper_balance.balance, Decimal("9900.00"))

    def test_copying_settled_coupon_settles_copied_bet_immediately(self):
        reader = User.objects.create_user(
            username="copy-finished-reader",
            password="safe-test-password",
            role=User.Role.READER,
        )
        activate_copybetting(
            user=reader,
            analyst=self.analyst,
            bank_amount=Decimal("1000.00"),
            stake_percent=Decimal("10.00"),
        )
        coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=PredictionCoupon.StateStatus.WIN,
            total_stake=Decimal("500.00"),
            possible_payout=Decimal("1000.00"),
            confidence=80,
            published_at=timezone.now(),
        )

        copied = copy_published_coupon(coupon)

        self.assertEqual(len(copied), 1)
        copied_bet = CopiedBet.objects.get(user=reader, source_coupon=coupon)
        self.assertEqual(copied_bet.state_status, CopiedBet.StateStatus.WIN)
        self.assertEqual(copied_bet.profit, Decimal("100.00"))
        reader.capper_balance.refresh_from_db()
        self.assertEqual(reader.capper_balance.balance, Decimal("10100.00"))
        subscription = CopyBettingSubscription.objects.get(user=reader, analyst=self.analyst)
        self.assertEqual(subscription.total_profit, Decimal("100.00"))

    def test_copied_bet_is_settled_with_source_coupon(self):
        reader = User.objects.create_user(
            username="copy-settle-reader",
            password="safe-test-password",
            role=User.Role.READER,
        )
        activate_copybetting(
            user=reader,
            analyst=self.analyst,
            bank_amount=Decimal("1000.00"),
            stake_percent=Decimal("10.00"),
            stop_loss_amount=Decimal("300.00"),
        )
        coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("500.00"),
            possible_payout=Decimal("1000.00"),
            confidence=80,
            published_at=timezone.now(),
        )
        Prediction.objects.create(
            coupon=coupon,
            match=self.match,
            market="winner",
            selection="Хозяева",
            coefficient=Decimal("2.00"),
            stake=Decimal("500.00"),
            state_status=Prediction.StateStatus.WIN,
        )
        copy_published_coupon(coupon)

        settle_coupon(coupon.id)

        copied_bet = CopiedBet.objects.get(user=reader, source_coupon=coupon)
        self.assertEqual(copied_bet.state_status, CopiedBet.StateStatus.WIN)
        self.assertEqual(copied_bet.profit, Decimal("100.00"))
        reader.capper_balance.refresh_from_db()
        self.assertEqual(reader.capper_balance.balance, Decimal("10100.00"))
        subscription = CopyBettingSubscription.objects.get(user=reader, analyst=self.analyst)
        self.assertEqual(subscription.total_profit, Decimal("100.00"))

    def test_settling_source_coupon_creates_missing_copied_bet(self):
        reader = User.objects.create_user(
            username="copy-missing-reader",
            password="safe-test-password",
            role=User.Role.READER,
        )
        activate_copybetting(
            user=reader,
            analyst=self.analyst,
            bank_amount=Decimal("1000.00"),
            stake_percent=Decimal("10.00"),
            stop_loss_amount=Decimal("300.00"),
        )
        coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("500.00"),
            possible_payout=Decimal("1000.00"),
            confidence=80,
            published_at=timezone.now(),
        )
        Prediction.objects.create(
            coupon=coupon,
            match=self.match,
            market="winner",
            selection="Хозяева",
            coefficient=Decimal("2.00"),
            stake=Decimal("500.00"),
            state_status=Prediction.StateStatus.WIN,
        )

        settle_coupon(coupon.id)

        copied_bet = CopiedBet.objects.get(user=reader, source_coupon=coupon)
        self.assertEqual(copied_bet.state_status, CopiedBet.StateStatus.WIN)
        self.assertEqual(copied_bet.profit, Decimal("100.00"))
        reader.capper_balance.refresh_from_db()
        self.assertEqual(reader.capper_balance.balance, Decimal("10100.00"))

    def test_copybetting_respects_pause_and_resume(self):
        reader = User.objects.create_user(
            username="copy-pause-reader",
            password="safe-test-password",
            role=User.Role.READER,
        )
        subscription = activate_copybetting(
            user=reader,
            analyst=self.analyst,
            bank_amount=Decimal("1000.00"),
            stake_percent=Decimal("10.00"),
        )
        pause_copybetting(subscription)
        coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("500.00"),
            possible_payout=Decimal("1000.00"),
            confidence=80,
            published_at=timezone.now(),
        )

        self.assertEqual(copy_published_coupon(coupon), [])

        resume_copybetting(subscription)
        self.assertFalse(CopiedBet.objects.filter(user=reader, source_coupon=coupon).exists())
        self.assertEqual(copy_published_coupon(coupon), [])

        new_coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("500.00"),
            possible_payout=Decimal("1000.00"),
            confidence=80,
            published_at=timezone.now(),
        )

        copied = copy_published_coupon(new_coupon)

        self.assertEqual(len(copied), 1)

    def test_pause_is_deferred_while_started_copied_bet_is_pending(self):
        reader = User.objects.create_user(
            username="copy-deferred-pause-reader",
            password="safe-test-password",
            role=User.Role.READER,
        )
        subscription = activate_copybetting(
            user=reader,
            analyst=self.analyst,
            bank_amount=Decimal("1000.00"),
            stake_percent=Decimal("10.00"),
        )
        coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("500.00"),
            possible_payout=Decimal("1000.00"),
            confidence=80,
            published_at=timezone.now(),
        )
        Prediction.objects.create(
            coupon=coupon,
            match=self.match,
            market="winner",
            selection="Хозяева",
            coefficient=Decimal("2.00"),
            stake=Decimal("500.00"),
            state_status=Prediction.StateStatus.WIN,
        )
        copy_published_coupon(coupon)
        self.match.starts_at = timezone.now() - timedelta(minutes=1)
        self.match.save(update_fields=["starts_at", "updated_at"])

        subscription = pause_copybetting(subscription)

        self.assertEqual(subscription.status, CopyBettingSubscription.Status.ACTIVE)
        self.assertEqual(subscription.pending_status, CopyBettingSubscription.Status.PAUSED)

        next_coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("500.00"),
            possible_payout=Decimal("1000.00"),
            confidence=80,
            published_at=timezone.now(),
        )
        self.assertEqual(copy_published_coupon(next_coupon), [])

        settle_coupon(coupon.id)

        subscription.refresh_from_db()
        self.assertEqual(subscription.status, CopyBettingSubscription.Status.PAUSED)
        self.assertEqual(subscription.pending_status, "")

    def test_stop_is_deferred_while_started_copied_bet_is_pending(self):
        reader = User.objects.create_user(
            username="copy-deferred-stop-reader",
            password="safe-test-password",
            role=User.Role.READER,
        )
        subscription = activate_copybetting(
            user=reader,
            analyst=self.analyst,
            bank_amount=Decimal("1000.00"),
            stake_percent=Decimal("10.00"),
        )
        coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("500.00"),
            possible_payout=Decimal("1000.00"),
            confidence=80,
            published_at=timezone.now(),
        )
        Prediction.objects.create(
            coupon=coupon,
            match=self.match,
            market="winner",
            selection="Хозяева",
            coefficient=Decimal("2.00"),
            stake=Decimal("500.00"),
            state_status=Prediction.StateStatus.WIN,
        )
        copy_published_coupon(coupon)
        self.match.starts_at = timezone.now() - timedelta(minutes=1)
        self.match.save(update_fields=["starts_at", "updated_at"])

        subscription = stop_copybetting(subscription)

        self.assertEqual(subscription.status, CopyBettingSubscription.Status.ACTIVE)
        self.assertEqual(subscription.pending_status, CopyBettingSubscription.Status.STOPPED)

        settle_coupon(coupon.id)

        subscription.refresh_from_db()
        self.assertEqual(subscription.status, CopyBettingSubscription.Status.STOPPED)
        self.assertEqual(subscription.pending_status, "")

    def test_copybetting_filters_by_minimum_total_coefficient(self):
        reader = User.objects.create_user(
            username="copy-min-coef-reader",
            password="safe-test-password",
            role=User.Role.READER,
        )
        activate_copybetting(
            user=reader,
            analyst=self.analyst,
            bank_amount=Decimal("1000.00"),
            stake_percent=Decimal("10.00"),
            min_total_coefficient=Decimal("2.50"),
        )
        coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("500.00"),
            possible_payout=Decimal("1000.00"),
            confidence=80,
            published_at=timezone.now(),
        )

        self.assertEqual(copy_published_coupon(coupon), [])
        self.assertFalse(CopiedBet.objects.filter(user=reader, source_coupon=coupon).exists())

    def test_copybetting_filters_by_allowed_sports(self):
        football = Sport.objects.create(code="football", name="Football", name_ru="Футбол")
        basketball = Sport.objects.create(code="basketball", name="Basketball", name_ru="Баскетбол")
        self.match.sport = football
        self.match.save(update_fields=["sport", "updated_at"])
        reader = User.objects.create_user(
            username="copy-sport-reader",
            password="safe-test-password",
            role=User.Role.READER,
        )
        subscription = activate_copybetting(
            user=reader,
            analyst=self.analyst,
            bank_amount=Decimal("1000.00"),
            stake_percent=Decimal("10.00"),
            allowed_sports=[basketball],
        )
        coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("500.00"),
            possible_payout=Decimal("1000.00"),
            confidence=80,
            published_at=timezone.now(),
        )
        Prediction.objects.create(
            coupon=coupon,
            match=self.match,
            market="winner",
            selection="Хозяева",
            coefficient=Decimal("2.00"),
            stake=Decimal("500.00"),
        )

        self.assertEqual(copy_published_coupon(coupon), [])

        subscription.allowed_sports.set([football])
        copied = copy_published_coupon(coupon)

        self.assertEqual(len(copied), 1)

    def test_copybetting_can_skip_tournament_coupons(self):
        reader = User.objects.create_user(
            username="copy-tournament-reader",
            password="safe-test-password",
            role=User.Role.READER,
        )
        activate_copybetting(
            user=reader,
            analyst=self.analyst,
            bank_amount=Decimal("1000.00"),
            stake_percent=Decimal("10.00"),
            copy_regular_coupons=True,
            copy_tournament_coupons=False,
        )
        tournament = Tournament.objects.create(
            title="Wallet Cup",
            status=Tournament.Status.PUBLISHED,
            starts_at=timezone.now() - timedelta(hours=1),
            ends_at=timezone.now() + timedelta(days=1),
        )
        participant = TournamentParticipant.objects.create(
            tournament=tournament,
            user=self.analyst,
        )
        coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("500.00"),
            possible_payout=Decimal("1000.00"),
            confidence=80,
            published_at=timezone.now(),
        )
        TournamentCoupon.objects.create(
            tournament=tournament,
            participant=participant,
            coupon=coupon,
        )

        self.assertEqual(copy_published_coupon(coupon), [])

    def test_paid_subscription_credits_analyst_real_balance(self):
        profile = AnalystProfile.objects.get(user=self.analyst)
        profile.paid_predictions_enabled = True
        profile.paid_predictions_price = Decimal("990.00")
        profile.save(update_fields=["paid_predictions_enabled", "paid_predictions_price", "updated_at"])
        reader = User.objects.create_user(
            username="paid-income-reader",
            password="safe-test-password",
            role=User.Role.READER,
        )

        subscribe_to_paid_predictions(reader, self.analyst)

        self.analyst.real_balance.refresh_from_db()
        self.assertEqual(self.analyst.real_balance.balance, Decimal("990.00"))
        self.assertTrue(
            RealBalanceTransaction.objects.filter(
                user=self.analyst,
                kind=RealBalanceTransaction.Kind.SUBSCRIPTION_INCOME,
                amount=Decimal("990.00"),
            ).exists()
        )

    def test_admin_can_approve_real_withdrawal(self):
        self.analyst.real_balance.balance = Decimal("1000.00")
        self.analyst.real_balance.save(update_fields=["balance", "updated_at"])
        request_real_withdrawal(self.analyst, Decimal("400.00"))
        withdrawal = RealBalanceTransaction.objects.get(
            user=self.analyst,
            kind=RealBalanceTransaction.Kind.WITHDRAWAL_REQUEST,
        )

        approve_real_withdrawal(withdrawal)

        withdrawal.refresh_from_db()
        self.analyst.real_balance.refresh_from_db()
        self.assertEqual(withdrawal.status, RealBalanceTransaction.Status.COMPLETED)
        self.assertEqual(self.analyst.real_balance.balance, Decimal("600.00"))
        self.assertEqual(self.analyst.real_balance.pending_withdrawal, Decimal("0.00"))

    def test_admin_can_cancel_real_withdrawal_and_refund_balance(self):
        self.analyst.real_balance.balance = Decimal("1000.00")
        self.analyst.real_balance.save(update_fields=["balance", "updated_at"])
        request_real_withdrawal(self.analyst, Decimal("400.00"))
        withdrawal = RealBalanceTransaction.objects.get(
            user=self.analyst,
            kind=RealBalanceTransaction.Kind.WITHDRAWAL_REQUEST,
        )

        cancel_real_withdrawal(withdrawal)

        withdrawal.refresh_from_db()
        self.analyst.real_balance.refresh_from_db()
        self.assertEqual(withdrawal.status, RealBalanceTransaction.Status.CANCELED)
        self.assertEqual(self.analyst.real_balance.balance, Decimal("1000.00"))
        self.assertEqual(self.analyst.real_balance.pending_withdrawal, Decimal("0.00"))
        self.assertTrue(
            RealBalanceTransaction.objects.filter(
                user=self.analyst,
                kind=RealBalanceTransaction.Kind.WITHDRAWAL_CANCEL,
                amount=Decimal("400.00"),
                related_id=withdrawal.id,
            ).exists()
        )


@override_settings(STORAGES=TEST_STORAGES)
class CapperBalanceHeaderTests(TestCase):
    def test_analyst_header_shows_balance_and_top_up_button(self):
        analyst = User.objects.create_user(
            username="header-balance-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.client.force_login(analyst)

        response = self.client.get(reverse("front:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="nav-wallet"')
        self.assertContains(response, 'class="nav-wallet-topup"')
        self.assertContains(response, "10 000 ₽")
        self.assertContains(response, reverse("wallets:top_up"))
        self.assertContains(response, "Пополнить")

    def test_top_up_link_opens_wallet_methods_page(self):
        analyst = User.objects.create_user(
            username="wallet-page-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.client.force_login(analyst)

        response = self.client.get(reverse("wallets:top_up"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Способы пополнения")
        self.assertContains(response, "Виртуальное пополнение")
        self.assertContains(response, "10 000 ₽")
