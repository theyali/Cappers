from datetime import timedelta
from decimal import Decimal

from django.contrib import admin
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cabinet.models import User
from game.admin import PredictionCouponAdmin, PredictionItemAdmin
from game.models import Match, Prediction, PredictionCoupon, PredictionCouponResultChange
from game.services.settlement import resettle_coupon, settle_coupon, settle_finished_matches
from wallets.models import CoinTransaction, CopiedBet, CopyBettingSubscription
from wallets.services import activate_copybetting, adjust_coin_balance, charge_prediction_stake, copy_published_coupon


TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

WIN = Prediction.StateStatus.WIN
LOSE = Prediction.StateStatus.LOSE
REFUND = Prediction.StateStatus.REFUND


class ResettlementTestCase(TestCase):
    def setUp(self):
        self.analyst = User.objects.create_user(
            username="resettle-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.match = Match.objects.create(
            external_id=778001,
            sync_scope=Match.SyncScope.FINISHED,
            starts_at=timezone.now() - timedelta(hours=3),
            score="2-1",
            raw_data={"teams": {"home": {"name": {"ru": "Хозяева"}}, "away": {"name": {"ru": "Гости"}}}},
        )
        self.coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("500"),
            possible_payout=Decimal("1000"),
            confidence=70,
            published_at=timezone.now() - timedelta(hours=4),
        )
        self.prediction = Prediction.objects.create(
            coupon=self.coupon,
            match=self.match,
            market="winner",
            selection="Хозяева",
            outcome_code="1",
            coefficient=Decimal("2.00"),
            stake=Decimal("500"),
        )
        charge_prediction_stake(self.analyst, self.coupon, self.coupon.total_stake)

    def _settle_as(self, state, **kwargs):
        Prediction.objects.filter(pk=self.prediction.pk).update(state_status=state)
        return settle_coupon(self.coupon.pk, **kwargs)

    def _balance(self, user=None):
        user = user or self.analyst
        user.coin_wallet.refresh_from_db()
        return user.coin_wallet.balance

    def _history(self):
        return list(
            self.coupon.result_changes.order_by("id").values_list(
                "previous_status",
                "new_status",
                "author_coins",
            )
        )

    def _amounts(self, kind, user=None):
        return list(
            CoinTransaction.objects.filter(user=user or self.analyst, kind=kind)
            .order_by("id")
            .values_list("amount", flat=True)
        )


class CouponResettlementTests(ResettlementTestCase):
    def test_win_changed_to_lose_takes_the_payout_back(self):
        self._settle_as(WIN)
        self.assertEqual(self._balance(), 1500)

        self._settle_as(LOSE)

        self.assertEqual(self._balance(), 500)
        self.assertEqual(self._amounts(CoinTransaction.Kind.PREDICTION_PAYOUT_REVERSAL), [-1000])
        self.assertEqual(
            self._history(),
            [("pending", "win", 1000), ("win", "lose", -1000)],
        )

    def test_result_can_flip_back_and_forth(self):
        self._settle_as(WIN)
        self._settle_as(LOSE)
        self._settle_as(WIN)
        self.assertEqual(self._balance(), 1500)

        self._settle_as(LOSE)

        self.assertEqual(self._balance(), 500)
        self.assertEqual(self._amounts(CoinTransaction.Kind.PREDICTION_PAYOUT), [1000, 1000])
        self.assertEqual(self._amounts(CoinTransaction.Kind.PREDICTION_PAYOUT_REVERSAL), [-1000, -1000])
        self.assertEqual(self.coupon.result_changes.count(), 4)

    def test_lose_changed_to_win_pays_out(self):
        self._settle_as(LOSE)
        self.assertEqual(self._balance(), 500)

        self._settle_as(WIN)

        self.assertEqual(self._balance(), 1500)

    def test_refund_and_win_are_settled_by_the_difference(self):
        self._settle_as(REFUND)
        self.assertEqual(self._balance(), 1000)

        self._settle_as(WIN)
        self.assertEqual(self._balance(), 1500)
        self.assertEqual(self._amounts(CoinTransaction.Kind.PREDICTION_PAYOUT), [500])

        self._settle_as(REFUND)
        self.assertEqual(self._balance(), 1000)
        self.assertEqual(self._amounts(CoinTransaction.Kind.PREDICTION_PAYOUT_REVERSAL), [-500])

    def test_changed_coefficient_corrects_the_payout(self):
        self._settle_as(WIN)

        Prediction.objects.filter(pk=self.prediction.pk).update(coefficient=Decimal("2.10"))
        settle_coupon(self.coupon.pk)

        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.possible_payout, Decimal("1050.00"))
        self.assertEqual(self._balance(), 1550)
        self.assertEqual(self._history()[-1], ("win", "win", 50))

    def test_repeated_settlement_changes_nothing(self):
        self._settle_as(WIN)
        updated_at = PredictionCoupon.objects.get(pk=self.coupon.pk).updated_at

        settle_coupon(self.coupon.pk)
        settle_coupon(self.coupon.pk)

        self.assertEqual(self._balance(), 1500)
        self.assertEqual(self.coupon.result_changes.count(), 1)
        self.assertEqual(PredictionCoupon.objects.get(pk=self.coupon.pk).updated_at, updated_at)

    def test_withdrawn_result_returns_coupon_to_pending(self):
        self._settle_as(WIN)

        self._settle_as("")

        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.state_status, PredictionCoupon.StateStatus.PENDING)
        self.assertIsNone(self.coupon.settled_at)
        self.assertEqual(self._balance(), 500)

        self._settle_as(WIN)
        self.assertEqual(self._balance(), 1500)

    def test_spent_payout_is_taken_back_up_to_the_balance(self):
        self._settle_as(WIN)
        adjust_coin_balance(self.analyst, -1400)

        self._settle_as(LOSE)

        self.assertEqual(self._balance(), 0)
        change = self.coupon.result_changes.order_by("id").last()
        self.assertEqual(change.author_coins, -100)
        self.assertEqual(change.uncollected_coins, 900)

        # The coins that were not taken back count when the result flips again.
        self._settle_as(WIN)
        self.assertEqual(self._balance(), 100)

    def test_corrected_match_score_is_resettled(self):
        settle_finished_matches()
        self.prediction.refresh_from_db()
        self.assertEqual(self.prediction.state_status, WIN)
        self.assertEqual(self._balance(), 1500)

        Match.objects.filter(pk=self.match.pk).update(score="0-1")
        resettle_coupon(self.coupon.pk)

        self.prediction.refresh_from_db()
        self.assertEqual(self.prediction.state_status, LOSE)
        self.assertEqual(self._balance(), 500)
        change = self.coupon.result_changes.order_by("id").last()
        self.assertEqual(change.source, PredictionCouponResultChange.Source.RESETTLE)


class CopiedBetResettlementTests(ResettlementTestCase):
    def setUp(self):
        super().setUp()
        self.reader = User.objects.create_user(
            username="resettle-reader",
            password="safe-test-password",
            role=User.Role.READER,
        )
        activate_copybetting(
            user=self.reader,
            analyst=self.analyst,
            bank_amount=Decimal("1000.00"),
            stake_percent=Decimal("10.00"),
            stop_loss_amount=Decimal("0"),
        )
        PredictionCoupon.objects.filter(pk=self.coupon.pk).update(published_at=timezone.now())
        self.coupon.refresh_from_db()
        self.assertEqual(len(copy_published_coupon(self.coupon)), 1)
        self.copied_bet = CopiedBet.objects.get(source_coupon=self.coupon)

    def _subscription(self):
        return CopyBettingSubscription.objects.get(user=self.reader)

    def test_copy_follows_the_changed_result(self):
        self.assertEqual(self._balance(self.reader), 900)
        self._settle_as(WIN)
        self.assertEqual(self._balance(self.reader), 1100)

        self._settle_as(LOSE)

        self.assertEqual(self._balance(self.reader), 900)
        self.copied_bet.refresh_from_db()
        self.assertEqual(self.copied_bet.state_status, CopiedBet.StateStatus.LOSE)
        self.assertEqual(self.copied_bet.profit, Decimal("-100"))
        subscription = self._subscription()
        self.assertEqual(subscription.total_profit, Decimal("-100"))
        self.assertEqual(subscription.current_loss, Decimal("100"))
        self.assertEqual(
            self._amounts(CoinTransaction.Kind.COPYBET_PAYOUT_REVERSAL, self.reader),
            [-200],
        )

        self._settle_as(WIN)

        self.assertEqual(self._balance(self.reader), 1100)
        subscription = self._subscription()
        self.assertEqual(subscription.total_profit, Decimal("100"))
        self.assertEqual(subscription.current_loss, Decimal("0"))
        self.assertEqual(self._amounts(CoinTransaction.Kind.COPYBET_PAYOUT, self.reader), [200, 200])

    def test_copy_returns_to_pending_with_the_coupon(self):
        self._settle_as(WIN)

        self._settle_as("")

        self.copied_bet.refresh_from_db()
        self.assertEqual(self.copied_bet.state_status, CopiedBet.StateStatus.PENDING)
        self.assertIsNone(self.copied_bet.settled_at)
        self.assertEqual(self._balance(self.reader), 900)
        self.assertEqual(self._subscription().total_profit, Decimal("0"))

    def test_follower_without_coins_is_reported_as_uncollected(self):
        self._settle_as(WIN)
        adjust_coin_balance(self.reader, -1050)

        self._settle_as(LOSE)

        self.assertEqual(self._balance(self.reader), 0)
        change = self.coupon.result_changes.order_by("id").last()
        self.assertEqual(change.uncollected_coins, 150)


@override_settings(STORAGES=TEST_STORAGES)
class CouponResultAdminTests(ResettlementTestCase):
    def setUp(self):
        super().setUp()
        self.admin_user = User.objects.create_superuser(
            username="resettle-admin",
            password="safe-test-password",
            email="resettle-admin@example.com",
        )
        self.request = RequestFactory().post("/")
        self.request.user = self.admin_user

    def test_position_result_edited_in_admin_settles_coins(self):
        self.prediction.state_status = WIN
        PredictionItemAdmin(Prediction, admin.site).save_model(self.request, self.prediction, None, True)

        self.assertEqual(self._balance(), 1500)
        change = self.coupon.result_changes.get()
        self.assertEqual(change.source, PredictionCouponResultChange.Source.ADMIN)
        self.assertEqual(change.changed_by, self.admin_user)

    def test_coupon_result_fields_are_read_only_after_publish(self):
        readonly_fields = PredictionCouponAdmin(PredictionCoupon, admin.site).get_readonly_fields(
            self.request,
            self.coupon,
        )

        self.assertIn("state_status", readonly_fields)
        self.assertIn("possible_payout", readonly_fields)

    def test_change_page_shows_result_history(self):
        self._settle_as(WIN)
        self.client.force_login(self.admin_user)

        response = self.client.get(reverse("admin:game_predictioncoupon_change", args=[self.coupon.pk]))

        self.assertContains(response, "История результатов прогноза")

    def test_resettle_action(self):
        self.client.force_login(self.admin_user)

        response = self.client.post(
            reverse("admin:game_predictioncoupon_changelist"),
            {"action": "resettle_by_match_results", "_selected_action": [self.coupon.pk]},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._balance(), 1500)
        self.assertEqual(self.coupon.result_changes.get().changed_by, self.admin_user)
