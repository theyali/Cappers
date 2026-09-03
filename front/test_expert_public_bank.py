from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from cabinet.models import AnalystProfile, User
from game.models import PredictionCoupon


class ExpertPublicBankTests(TestCase):
    def setUp(self):
        self.expert = User.objects.create_user(
            username="bank-expert",
            password="test-password",
            role=User.Role.ANALYST,
        )
        AnalystProfile.objects.create(
            user=self.expert,
            display_name="Bank Expert",
            is_public=True,
        )

        PredictionCoupon.objects.create(
            author=self.expert,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=PredictionCoupon.StateStatus.WIN,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("180.00"),
        )
        PredictionCoupon.objects.create(
            author=self.expert,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=PredictionCoupon.StateStatus.LOSE,
            total_stake=Decimal("50.00"),
            possible_payout=Decimal("0.00"),
        )
        PredictionCoupon.objects.create(
            author=self.expert,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=PredictionCoupon.StateStatus.PENDING,
            total_stake=Decimal("150.00"),
            possible_payout=Decimal("300.00"),
        )

    def test_public_profile_has_bank_tab_with_all_time_money_metrics(self):
        response = self.client.get(
            reverse("front:expert_profile", kwargs={"username": self.expert.username})
        )

        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn('data-expert-public-tab="bank"', html)
        self.assertIn('data-expert-public-panel="bank"', html)
        self.assertIn("Сыграно за всё время", html)
        self.assertIn("300 ₽", html)
        self.assertIn("Проиграно", html)
        self.assertIn("50 ₽", html)
        self.assertIn("Заработано", html)
        self.assertIn("80 ₽", html)
        self.assertIn("Чистый результат", html)
        self.assertIn("+30 ₽", html)
        self.assertIn("Средняя ставка", html)
        self.assertIn("100 ₽", html)
        self.assertIn("Сейчас в игре", html)
        self.assertIn("150 ₽", html)
