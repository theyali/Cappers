import json
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db.models import ProtectedError, RestrictedError
from django.db.models.deletion import Collector
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cabinet.models import User
from cabinet.roulette.rewards import UserRouletteRewardState
from game.models import Match, MatchOdds, PredictionCoupon
from game.services.settlement import cancel_published_coupon
from game.views import _delete_expired_draft_coupons
from wallets.models import CoinTransaction, CopiedBet
from wallets.services import activate_copybetting, settle_orphaned_copied_bets


TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


class CouponCancelTestMixin:
    def setUp(self):
        self.analyst = User.objects.create_user(
            username="cancel-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.reader = User.objects.create_user(
            username="cancel-copier",
            password="safe-test-password",
            role=User.Role.READER,
        )
        self.match = Match.objects.create(
            external_id=774001,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now() + timedelta(hours=2),
            raw_data={
                "teams": {
                    "home": {"name": {"ru": "Арсенал"}},
                    "away": {"name": {"ru": "Челси"}},
                },
            },
        )
        MatchOdds.objects.create(match=self.match, home_win_bet=1.85)
        activate_copybetting(
            user=self.reader,
            analyst=self.analyst,
            bank_amount=1000,
            stake_percent=10,
        )

    def _publish(self, **payload_overrides):
        payload = {
            "stake": "500",
            "confidence": 70,
            "items": [
                {
                    "match_id": self.match.id,
                    "market": "winner",
                    "selection": "Арсенал",
                    "coefficient": "1.85",
                }
            ],
        }
        payload.update(payload_overrides)
        self.client.force_login(self.analyst)
        response = self.client.post(
            reverse("game:create_coupon"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        return PredictionCoupon.objects.get(pk=response.json()["coupon_id"])

    def _balance(self, user):
        user.coin_wallet.refresh_from_db()
        return user.coin_wallet.balance


class CancelPublishedCouponTests(CouponCancelTestMixin, TestCase):
    def test_cancel_refunds_author_and_copiers(self):
        coupon = self._publish()
        copied_bet = CopiedBet.objects.get(source_coupon=coupon)
        self.assertEqual(self._balance(self.analyst), 500)
        self.assertEqual(self._balance(self.reader), 900)

        cancel_published_coupon(coupon.pk, reason="ошибка в купоне")

        coupon.refresh_from_db()
        copied_bet.refresh_from_db()
        self.assertEqual(coupon.published_status, PredictionCoupon.PublishedStatus.CANCELED)
        self.assertEqual(copied_bet.state_status, CopiedBet.StateStatus.REFUND)
        self.assertEqual(self._balance(self.analyst), 1000)
        self.assertEqual(self._balance(self.reader), 1000)
        refund = CoinTransaction.objects.get(
            user=self.analyst,
            kind=CoinTransaction.Kind.PREDICTION_REFUND,
            related_id=coupon.pk,
        )
        self.assertEqual(refund.amount, 500)
        self.assertIn("ошибка в купоне", refund.note)

    def test_coupon_can_be_canceled_only_once(self):
        coupon = self._publish()
        cancel_published_coupon(coupon.pk)

        with self.assertRaisesMessage(ValidationError, "только опубликованный"):
            cancel_published_coupon(coupon.pk)

        self.assertEqual(self._balance(self.analyst), 1000)

    def test_settled_coupon_cannot_be_canceled(self):
        coupon = self._publish()
        PredictionCoupon.objects.filter(pk=coupon.pk).update(
            state_status=PredictionCoupon.StateStatus.LOSE,
        )

        with self.assertRaisesMessage(ValidationError, "Рассчитанный прогноз"):
            cancel_published_coupon(coupon.pk)

        coupon.refresh_from_db()
        self.assertEqual(coupon.published_status, PredictionCoupon.PublishedStatus.PUBLISHED)
        self.assertEqual(self._balance(self.analyst), 500)

    def test_cancel_returns_free_roulette_prediction(self):
        UserRouletteRewardState.objects.create(user=self.analyst, free_predictions=1)
        coupon = self._publish(stake="100", use_free_prediction=True)
        self.assertEqual(UserRouletteRewardState.objects.get(user=self.analyst).free_predictions, 0)

        cancel_published_coupon(coupon.pk)

        self.assertEqual(UserRouletteRewardState.objects.get(user=self.analyst).free_predictions, 1)
        self.assertEqual(self._balance(self.analyst), 1000)
        self.assertFalse(
            CoinTransaction.objects.filter(
                user=self.analyst,
                kind=CoinTransaction.Kind.PREDICTION_REFUND,
            ).exists()
        )


class CopiedBetsOfVoidedCouponTests(CouponCancelTestMixin, TestCase):
    def _unpublish_like_legacy_editor(self, coupon):
        PredictionCoupon.objects.filter(pk=coupon.pk).update(
            published_status=PredictionCoupon.PublishedStatus.DRAFT,
            updated_at=timezone.now() - timedelta(days=60),
        )

    def test_orphaned_copies_of_unpublished_coupon_are_refunded(self):
        coupon = self._publish()
        self._unpublish_like_legacy_editor(coupon)

        settled = settle_orphaned_copied_bets()

        self.assertEqual(settled, 1)
        copied_bet = CopiedBet.objects.get(source_coupon=coupon)
        self.assertEqual(copied_bet.state_status, CopiedBet.StateStatus.REFUND)
        self.assertEqual(self._balance(self.reader), 1000)

    def test_draft_cleanup_keeps_coupon_with_copied_bets(self):
        coupon = self._publish()
        self._unpublish_like_legacy_editor(coupon)

        _delete_expired_draft_coupons(self.analyst)

        self.assertTrue(PredictionCoupon.objects.filter(pk=coupon.pk).exists())
        with self.assertRaises(RestrictedError):
            coupon.delete()

    def test_author_account_with_copied_bets_cannot_be_hard_deleted(self):
        self._publish()

        # Accounts are deleted by anonymizing them; financial records keep the user.
        with self.assertRaises(ProtectedError):
            Collector(using="default").collect([self.analyst])


@override_settings(STORAGES=TEST_STORAGES)
class CouponAdminCancelTests(CouponCancelTestMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser(
            username="coupon-admin",
            password="safe-test-password",
            email="admin@example.com",
        )

    def test_admin_cannot_change_status_of_published_coupon_directly(self):
        coupon = self._publish()
        self.client.force_login(self.admin)

        response = self.client.get(reverse("admin:game_predictioncoupon_change", args=[coupon.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'name="published_status"')
        self.assertNotContains(response, 'name="total_stake"')

    def test_admin_action_cancels_with_refund(self):
        coupon = self._publish()
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("admin:game_predictioncoupon_changelist"),
            {"action": "cancel_with_refund", "_selected_action": [coupon.pk]},
            follow=True,
        )

        self.assertContains(response, "Отменено прогнозов: 1.")
        coupon.refresh_from_db()
        self.assertEqual(coupon.published_status, PredictionCoupon.PublishedStatus.CANCELED)
        self.assertEqual(self._balance(self.analyst), 1000)
        self.assertEqual(self._balance(self.reader), 1000)
