from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from cabinet.models import User
from game.models import League, Match, Prediction, PredictionCoupon, Sport


class PredictionMoneyUiTests(TestCase):
    def setUp(self):
        self.analyst = User.objects.create_user(
            username="money-expert",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.sport = Sport.objects.create(
            external_id=30101,
            code="money-football",
            name="Football",
            name_ru="Футбол",
        )
        self.league = League.objects.create(
            external_id=30102,
            sport=self.sport,
            name="Money League",
            name_ru="Денежная лига",
        )
        self.match = Match.objects.create(
            external_id=30103,
            sport=self.sport,
            league=self.league,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now(),
            raw_data={
                "teams": {
                    "home": {"name": {"ru": "Хозяева"}},
                    "away": {"name": {"ru": "Гости"}},
                }
            },
        )
        self.coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=PredictionCoupon.StateStatus.PENDING,
            total_stake=Decimal("500.00"),
            possible_payout=Decimal("850.00"),
            confidence=70,
            published_at=timezone.now(),
        )
        Prediction.objects.create(
            coupon=self.coupon,
            match=self.match,
            market="winner",
            selection="Хозяева",
            coefficient=Decimal("1.70"),
            stake=Decimal("500.00"),
        )

    def test_prediction_card_shows_amount_and_coupon_value_in_rubles(self):
        response = self.client.get(reverse("front:predictions"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Сумма")
        self.assertContains(response, "500 ₽")
        self.assertContains(response, "Стоимость купона")
        self.assertContains(response, "850 ₽")
        self.assertContains(response, 'class="prediction-card-money"')

    def test_coupon_editor_exposes_min_max_rubles_and_constraint_script(self):
        self.client.force_login(self.analyst)
        response = self.client.get(reverse("game:match_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="stake" min="100" max="1000000"')
        self.assertContains(response, "От 100 ₽ до 1 000 000 ₽")
        self.assertContains(response, "Стоимость купона")
        self.assertContains(response, "coupon-constraints.js")

    def test_profile_coupon_list_uses_same_ruble_labels(self):
        self.client.force_login(self.analyst)
        response = self.client.get(reverse("cabinet:profile"), {"tab": "predictions"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Сумма")
        self.assertContains(response, "500.00 ₽")
        self.assertContains(response, "Стоимость купона")
        self.assertContains(response, "850.00 ₽")
