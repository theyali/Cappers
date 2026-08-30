from datetime import date, datetime
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from cabinet.models import AnalystProfile, CapperMonthlyStat, User
from game.models import PredictionCoupon


class CapperMonthlyStatsTests(TestCase):
    def setUp(self):
        self.analyst = User.objects.create_user(
            username="monthly_expert",
            password="test-password",
            role=User.Role.ANALYST,
        )
        self.profile = AnalystProfile.objects.get(user=self.analyst)
        self.profile.display_name = "Monthly Expert"
        self.profile.is_public = True
        self.profile.save(update_fields=["display_name", "is_public", "updated_at"])

    def _moment(self, year, month, day):
        value = datetime(year, month, day, 12, 0, 0)
        if timezone.is_aware(timezone.now()):
            return timezone.make_aware(value, timezone.get_current_timezone())
        return value

    def _coupon(self, state, stake, payout, settled_at):
        return PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=state,
            total_stake=Decimal(str(stake)),
            possible_payout=Decimal(str(payout)),
            published_at=settled_at,
            settled_at=settled_at,
        )

    def test_settled_coupons_persist_monthly_snapshot(self):
        august = self._moment(2026, 8, 10)
        self._coupon(PredictionCoupon.StateStatus.WIN, 100, 190, august)
        self._coupon(PredictionCoupon.StateStatus.LOSE, 200, 380, august)
        self._coupon(PredictionCoupon.StateStatus.REFUND, 100, 190, august)

        stat = CapperMonthlyStat.objects.get(
            analyst=self.analyst,
            month=date(2026, 8, 1),
        )

        self.assertEqual(stat.bets_count, 3)
        self.assertEqual(stat.wins_count, 1)
        self.assertEqual(stat.losses_count, 1)
        self.assertEqual(stat.refunds_count, 1)
        self.assertEqual(stat.total_stake, Decimal("400.00"))
        self.assertEqual(stat.total_profit, Decimal("-110.00"))
        self.assertEqual(stat.flat_profit_percent, Decimal("-3.33"))
        self.assertEqual(stat.roi, Decimal("-27.50"))
        self.assertEqual(stat.avg_coefficient, Decimal("1.90"))
        self.assertEqual(stat.hit_rate, Decimal("33.33"))

    def test_editing_result_month_rebuilds_old_and_new_history(self):
        coupon = self._coupon(
            PredictionCoupon.StateStatus.WIN,
            100,
            200,
            self._moment(2026, 7, 31),
        )
        self.assertTrue(
            CapperMonthlyStat.objects.filter(
                analyst=self.analyst,
                month=date(2026, 7, 1),
            ).exists()
        )

        coupon.settled_at = self._moment(2026, 8, 1)
        coupon.save(update_fields=["settled_at", "updated_at"])

        self.assertFalse(
            CapperMonthlyStat.objects.filter(
                analyst=self.analyst,
                month=date(2026, 7, 1),
            ).exists()
        )
        self.assertTrue(
            CapperMonthlyStat.objects.filter(
                analyst=self.analyst,
                month=date(2026, 8, 1),
            ).exists()
        )

    def test_public_profile_renders_monthly_history_from_database(self):
        CapperMonthlyStat.objects.create(
            analyst=self.analyst,
            month=date(2026, 8, 1),
            bets_count=7,
            wins_count=2,
            losses_count=4,
            refunds_count=1,
            total_stake=Decimal("700.00"),
            total_profit=Decimal("25.00"),
            flat_profit_percent=Decimal("3.50"),
            roi=Decimal("3.57"),
            avg_coefficient=Decimal("1.90"),
            hit_rate=Decimal("28.57"),
        )

        response = self.client.get(
            reverse("front:expert_profile", kwargs={"username": self.analyst.username})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Статистика по месяцам")
        self.assertContains(response, "Август 2026")
        self.assertContains(response, 'data-expert-monthly-stats')
        self.assertContains(response, "front/css/main.css")
        self.assertContains(response, "expert-monthly-stats.js")
        self.assertContains(response, "₽")
