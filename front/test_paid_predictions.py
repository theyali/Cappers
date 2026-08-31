from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cabinet.models import AnalystPaidSubscription, User
from game.models import League, Match, Prediction, PredictionCoupon, Sport


TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(STORAGES=TEST_STORAGES)
class PaidPredictionsVisibilityTests(TestCase):
    def setUp(self):
        self.sport = Sport.objects.create(
            external_id=2601,
            code="football-paid-test",
            name="Football",
            name_ru="Футбол",
        )
        self.league = League.objects.create(
            external_id=2602,
            sport=self.sport,
            name="Paid League",
            name_ru="Платная лига",
        )
        self.analyst = User.objects.create_user(
            username="paid-expert",
            password="test-password",
            role=User.Role.ANALYST,
        )
        profile = self.analyst.analyst_profile
        profile.display_name = "Paid Expert"
        profile.paid_predictions_enabled = True
        profile.paid_predictions_price = Decimal("1990.00")
        profile.save(
            update_fields=[
                "display_name",
                "paid_predictions_enabled",
                "paid_predictions_price",
                "updated_at",
            ]
        )
        self.reader = User.objects.create_user(
            username="paid-reader",
            password="test-password",
            role=User.Role.READER,
        )

    def _coupon(self, *, is_paid):
        match = Match.objects.create(
            external_id=2700 + int(is_paid),
            sport=self.sport,
            league=self.league,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now() + timedelta(days=1),
            raw_data={
                "teams": {
                    "home": {"name": {"ru": "Хозяева"}},
                    "away": {"name": {"ru": "Гости"}},
                }
            },
        )
        coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=PredictionCoupon.StateStatus.PENDING,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("190.00"),
            confidence=80,
            published_at=timezone.now(),
            is_paid=is_paid,
        )
        Prediction.objects.create(
            coupon=coupon,
            match=match,
            market="winner",
            selection="П1",
            coefficient=Decimal("1.90"),
            stake=Decimal("100.00"),
        )
        return coupon

    def test_paid_predictions_are_hidden_from_public_catalog_and_home(self):
        paid_coupon = self._coupon(is_paid=True)

        predictions_response = self.client.get(reverse("front:predictions"))
        self.assertEqual(predictions_response.status_code, 200)
        self.assertNotIn(
            paid_coupon.id,
            [item.id for item in predictions_response.context["page_obj"].object_list],
        )
        self.assertNotContains(predictions_response, "П1")

        home_response = self.client.get(reverse("front:index"))
        self.assertEqual(home_response.status_code, 200)
        self.assertEqual(home_response.context["latest_predictions"], [])

    def test_paid_prediction_detail_requires_active_subscription(self):
        paid_coupon = self._coupon(is_paid=True)

        response = self.client.get(
            reverse("front:prediction_detail", kwargs={"prediction_id": paid_coupon.id})
        )
        self.assertEqual(response.status_code, 404)

        AnalystPaidSubscription.objects.create(
            subscriber=self.reader,
            analyst=self.analyst,
            price=Decimal("1990.00"),
            starts_at=timezone.now(),
            expires_at=timezone.now() + timedelta(days=30),
        )
        self.client.force_login(self.reader)

        response = self.client.get(
            reverse("front:prediction_detail", kwargs={"prediction_id": paid_coupon.id})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "П1")

    def test_paid_subscription_adds_separate_feed_block(self):
        paid_coupon = self._coupon(is_paid=True)
        AnalystPaidSubscription.objects.create(
            subscriber=self.reader,
            analyst=self.analyst,
            price=Decimal("1990.00"),
            starts_at=timezone.now(),
            expires_at=timezone.now() + timedelta(days=30),
        )
        self.client.force_login(self.reader)

        response = self.client.get(reverse("front:following_feed"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["paid_predictions_count"], 1)
        self.assertEqual(response.context["paid_predictions"][0].id, paid_coupon.id)
        self.assertContains(response, "paid-feed-block")
        self.assertContains(response, "Закрытые прогнозы")

    def test_public_expert_page_shows_paid_placeholder(self):
        self._coupon(is_paid=True)

        response = self.client.get(
            reverse("front:expert_profile", kwargs={"username": self.analyst.username})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "predictions-grid expert-public-grid")
        self.assertContains(response, "Прогнозы платные")
        self.assertContains(response, "1990 ₽ / месяц")
        self.assertNotContains(response, "П1")
