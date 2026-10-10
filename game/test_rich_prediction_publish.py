from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cabinet.models import User, UserVipSubscription
from game.models import Match, MatchOdds, Prediction, PredictionCoupon
from game.services.coupon_validation import CouponMatchVerificationError
from game.services.prediction_editor import update_rich_prediction
from game.services.settlement import settle_coupon
from wallets.models import CoinTransaction


TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(STORAGES=TEST_STORAGES)
class RichPredictionPublishTests(TestCase):
    def setUp(self):
        self.analyst = User.objects.create_user(
            username="rich-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        UserVipSubscription.objects.create(
            user=self.analyst,
            starts_at=timezone.now() - timedelta(minutes=1),
            ends_at=timezone.now() + timedelta(days=30),
            duration_days=30,
            source=UserVipSubscription.Source.ADMIN,
        )
        self.match = Match.objects.create(
            external_id=773001,
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
        self.coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            prediction_format=PredictionCoupon.PredictionFormat.QUICK,
            published_status=PredictionCoupon.PublishedStatus.DRAFT,
            total_stake=Decimal("500"),
            possible_payout=Decimal("925.00"),
            confidence=70,
        )
        self.prediction = Prediction.objects.create(
            coupon=self.coupon,
            match=self.match,
            market="winner",
            selection="Арсенал",
            coefficient=Decimal("1.85"),
            stake=Decimal("500"),
        )
        self.client.force_login(self.analyst)

    def _form(self, **overrides):
        data = {
            "total_stake": "500",
            "confidence": "70",
            "headline": "Арсенал дома сильнее",
            "published_status": PredictionCoupon.PublishedStatus.PUBLISHED,
        }
        data.update(overrides)
        return data

    def _publish(self, **overrides):
        return self.client.post(reverse("game:rich_prediction_create"), self._form(**overrides))

    def _edit(self, **overrides):
        return self.client.post(
            reverse("game:rich_prediction_edit", kwargs={"coupon_id": self.coupon.pk}),
            self._form(**overrides),
        )

    def _stake_transactions(self):
        return CoinTransaction.objects.filter(
            user=self.analyst,
            kind=CoinTransaction.Kind.PREDICTION_STAKE,
        )

    def _balance(self):
        self.analyst.coin_wallet.refresh_from_db()
        return self.analyst.coin_wallet.balance

    def test_publish_charges_stake_once(self):
        response = self._publish()

        self.assertRedirects(
            response,
            reverse("game:rich_prediction_edit", kwargs={"coupon_id": self.coupon.pk}),
            fetch_redirect_response=False,
        )
        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.published_status, PredictionCoupon.PublishedStatus.PUBLISHED)
        self.assertEqual(self.coupon.prediction_format, PredictionCoupon.PredictionFormat.RICH)
        self.assertEqual(self._balance(), 500)
        self.assertEqual(list(self._stake_transactions().values_list("amount", flat=True)), [-500])

        self._edit(headline="Обновлённый заголовок")

        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.headline, "Обновлённый заголовок")
        self.assertEqual(self._balance(), 500)
        self.assertEqual(self._stake_transactions().count(), 1)

    def test_publish_backfills_outcome_code_of_old_drafts(self):
        self.assertEqual(self.prediction.outcome_code, "")

        self._publish()

        self.prediction.refresh_from_db()
        self.assertEqual(self.prediction.outcome_code, "1")

    def test_publish_without_enough_coins_keeps_draft(self):
        response = self._publish(total_stake="1500")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Недостаточно коинов")
        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.published_status, PredictionCoupon.PublishedStatus.DRAFT)
        self.assertEqual(self.coupon.prediction_format, PredictionCoupon.PredictionFormat.QUICK)
        self.assertFalse(self._stake_transactions().exists())
        self.assertEqual(self._balance(), 1000)

    def test_publish_after_kickoff_is_rejected(self):
        Match.objects.filter(pk=self.match.pk).update(starts_at=timezone.now() - timedelta(minutes=1))

        response = self._publish()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "уже начался или скоро начнется")
        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.published_status, PredictionCoupon.PublishedStatus.DRAFT)
        self.assertFalse(self._stake_transactions().exists())

    def test_provider_outage_is_reported_as_form_error(self):
        with patch(
            "game.services.prediction_editor.verify_matches_for_coupon",
            side_effect=CouponMatchVerificationError("Сервис спортивных данных временно недоступен."),
        ):
            response = self._publish()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Сервис спортивных данных временно недоступен.")
        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.published_status, PredictionCoupon.PublishedStatus.DRAFT)

    def test_changed_line_updates_draft_and_requires_confirmation(self):
        MatchOdds.objects.filter(match=self.match).update(home_win_bet=2.05)

        response = self._publish()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Коэффициенты изменились")
        self.prediction.refresh_from_db()
        self.assertEqual(self.prediction.coefficient, Decimal("2.05"))
        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.published_status, PredictionCoupon.PublishedStatus.DRAFT)
        self.assertFalse(self._stake_transactions().exists())

        self._publish()

        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.published_status, PredictionCoupon.PublishedStatus.PUBLISHED)
        self.assertEqual(self.coupon.possible_payout, Decimal("1025.00"))
        self.assertEqual(self._balance(), 500)

    def test_outcome_missing_from_line_blocks_publish(self):
        MatchOdds.objects.filter(match=self.match).update(home_win_bet=None, x_bet=3.4)

        response = self._publish()

        self.assertContains(response, "сейчас недоступен")
        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.published_status, PredictionCoupon.PublishedStatus.DRAFT)

    def test_published_coupon_keeps_stake_positions_and_status(self):
        self._publish()

        page = self.client.get(reverse("game:rich_prediction_edit", kwargs={"coupon_id": self.coupon.pk}))
        self.assertContains(page, "Сохранить изменения")
        self.assertNotContains(page, "Сохранить черновик")
        self.assertNotContains(page, "data-rich-remove-prediction")

        self._edit(total_stake="100000")
        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.total_stake, Decimal("500.00"))

        response = self._edit(remove_prediction_ids=str(self.prediction.pk))
        self.assertContains(response, "Позиции опубликованного прогноза изменить нельзя.")
        self.assertTrue(Prediction.objects.filter(pk=self.prediction.pk).exists())

        response = self._edit(published_status=PredictionCoupon.PublishedStatus.DRAFT)
        self.assertContains(response, "нельзя вернуть в черновик")
        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.published_status, PredictionCoupon.PublishedStatus.PUBLISHED)
        self.assertEqual(self._balance(), 500)

    def test_service_rejects_stake_change_after_publish(self):
        self._publish()
        self.coupon.refresh_from_db()

        with self.assertRaises(ValidationError) as caught:
            update_rich_prediction(
                self.analyst,
                self.coupon,
                {"total_stake": Decimal("100000"), "published_status": "published"},
                {},
            )

        self.assertIn("total_stake", caught.exception.message_dict)
        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.total_stake, Decimal("500.00"))

    def test_service_rejects_audience_change_after_publish(self):
        self._publish()
        self.coupon.refresh_from_db()

        with self.assertRaises(ValidationError) as caught:
            update_rich_prediction(
                self.analyst,
                self.coupon,
                {"is_paid": True, "published_status": "published"},
                {},
            )

        self.assertIn("is_paid", caught.exception.message_dict)
        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.audience, PredictionCoupon.Audience.FREE)

    def test_editor_cannot_cancel_coupon(self):
        self._publish()
        self.coupon.refresh_from_db()

        with self.assertRaises(ValidationError):
            update_rich_prediction(
                self.analyst,
                self.coupon,
                {"published_status": PredictionCoupon.PublishedStatus.CANCELED},
                {},
            )

        self.coupon.refresh_from_db()
        self.assertEqual(self.coupon.published_status, PredictionCoupon.PublishedStatus.PUBLISHED)


class UnpaidCouponSettlementTests(TestCase):
    def test_missing_coins_do_not_block_settlement(self):
        analyst = User.objects.create_user(
            username="unpaid-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        match = Match.objects.create(
            external_id=773101,
            sync_scope=Match.SyncScope.FINISHED,
            starts_at=timezone.now() - timedelta(hours=3),
        )
        coupon = PredictionCoupon.objects.create(
            author=analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("5000"),
            possible_payout=Decimal("9250.00"),
            confidence=70,
            published_at=timezone.now() - timedelta(hours=4),
        )
        Prediction.objects.create(
            coupon=coupon,
            match=match,
            market="winner",
            selection="Хозяева",
            coefficient=Decimal("1.85"),
            stake=Decimal("5000"),
            state_status=Prediction.StateStatus.WIN,
        )

        settle_coupon(coupon.pk)

        coupon.refresh_from_db()
        self.assertEqual(coupon.state_status, PredictionCoupon.StateStatus.WIN)
        self.assertIsNotNone(coupon.settled_at)
        analyst.coin_wallet.refresh_from_db()
        self.assertEqual(analyst.coin_wallet.balance, 1000)
        self.assertFalse(
            CoinTransaction.objects.filter(
                user=analyst,
                kind__in=(
                    CoinTransaction.Kind.PREDICTION_STAKE,
                    CoinTransaction.Kind.PREDICTION_PAYOUT,
                ),
            ).exists()
        )
