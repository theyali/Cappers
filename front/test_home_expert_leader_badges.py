from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cabinet.models import CapperMonthlyStat, User
from game.models import PredictionCoupon


TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(STORAGES=TEST_STORAGES)
class HomeExpertLeaderBadgesTests(TestCase):
    def _analyst(self, username):
        user = User.objects.create_user(
            username=username,
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        profile = user.analyst_profile
        profile.is_public = True
        profile.save(update_fields=["is_public", "updated_at"])
        return user

    def _coupon(self, author, *, payout):
        return PredictionCoupon.objects.create(
            author=author,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=PredictionCoupon.StateStatus.WIN,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal(payout),
            published_at=timezone.now() - timedelta(days=60),
            settled_at=timezone.now() - timedelta(days=60),
        )

    def test_home_sidebar_uses_current_month_top_when_available(self):
        all_time = self._analyst("all-time-leader")
        month = self._analyst("month-leader")

        for _ in range(8):
            self._coupon(all_time, payout="140.00")

        current_month = timezone.localdate().replace(day=1)
        CapperMonthlyStat.objects.create(
            analyst=month,
            month=current_month,
            bets_count=4,
            wins_count=3,
            losses_count=1,
            total_stake=Decimal("400.00"),
            total_profit=Decimal("160.00"),
            flat_profit_percent=Decimal("40.00"),
            roi=Decimal("40.00"),
            avg_coefficient=Decimal("1.80"),
            hit_rate=Decimal("75.00"),
        )

        response = self.client.get(reverse("front:index"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["top_experts_scope"], "month")
        self.assertEqual(response.context["top_experts"][0]["username"], month.username)
        self.assertContains(response, "Топовые эксперты месяца")
        self.assertContains(response, 'class="expert-leader-badge is-month"')
        self.assertContains(response, 'class="expert-leader-badge is-all-time"')

    def test_home_sidebar_falls_back_to_all_time_without_current_month_stats(self):
        all_time = self._analyst("fallback-leader")
        challenger = self._analyst("fallback-challenger")

        for _ in range(8):
            self._coupon(all_time, payout="130.00")
        self._coupon(challenger, payout="190.00")

        response = self.client.get(reverse("front:index"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["top_experts_scope"], "all_time")
        self.assertEqual(response.context["top_experts"][0]["username"], all_time.username)
        self.assertContains(response, "ВСЁ ВРЕМЯ")
        self.assertContains(response, 'class="expert-leader-badge is-all-time"')
