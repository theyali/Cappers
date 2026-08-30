from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from cabinet.models import User
from front.prediction_views import _prediction_card, _published_queryset
from game.models import Match, Prediction, PredictionCoupon


class PublicPredictionDetailTests(TestCase):
    def setUp(self):
        self.analyst = User.objects.create_user(
            username="public_coupon_analyst",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.matches = [
            Match.objects.create(
                external_id=994001 + index,
                sync_scope=Match.SyncScope.PREMATCH,
            )
            for index in range(2)
        ]
        self.coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("10.00"),
            possible_payout=Decimal("35.20"),
            confidence=67,
            published_at=timezone.now(),
        )
        Prediction.objects.create(
            coupon=self.coupon,
            match=self.matches[0],
            market="winner",
            selection="Хозяева",
            coefficient=Decimal("1.60"),
            stake=Decimal("10.00"),
        )
        Prediction.objects.create(
            coupon=self.coupon,
            match=self.matches[1],
            market="total",
            selection="ТБ 2.5",
            coefficient=Decimal("2.20"),
            stake=Decimal("10.00"),
        )

    def test_combined_coefficient_is_normalized_to_two_decimals(self):
        coupon = _published_queryset().get(pk=self.coupon.pk)
        card = _prediction_card(coupon)

        self.assertEqual(card.coefficient, Decimal("3.52"))
        self.assertEqual(card.positions_count, 2)

    def test_public_coupon_page_is_available_without_login(self):
        response = self.client.get(
            reverse("front:prediction_detail", kwargs={"prediction_id": self.coupon.id})
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_coefficient"], Decimal("3.52"))
        self.assertContains(response, "Купон #")
        self.assertContains(response, "Коэффициент:")
        self.assertContains(response, "Уверенность:")
        self.assertContains(response, "67%")
        self.assertContains(response, "Хозяева")
        self.assertContains(response, "ТБ 2.5")
        self.assertContains(response, "front/css/main.css")
        self.assertNotContains(response, "prediction-detail.css")

    def test_prediction_card_links_to_public_coupon(self):
        response = self.client.get(reverse("front:predictions"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Смотреть купон")
        self.assertContains(
            response,
            reverse("front:prediction_detail", kwargs={"prediction_id": self.coupon.id}),
        )

    def test_draft_coupon_has_no_public_page(self):
        draft = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.DRAFT,
            total_stake=Decimal("10.00"),
            possible_payout=Decimal("20.00"),
            confidence=50,
        )

        response = self.client.get(
            reverse("front:prediction_detail", kwargs={"prediction_id": draft.id})
        )

        self.assertEqual(response.status_code, 404)
