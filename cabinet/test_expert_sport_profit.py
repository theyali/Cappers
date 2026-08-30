from datetime import date, datetime
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from cabinet.models import AnalystProfile, CapperMonthlyStat, User
from game.models import Match, Prediction, PredictionCoupon, Sport


class ExpertSportProfitTests(TestCase):
    def setUp(self):
        self.analyst = User.objects.create_user(
            username="sport_profit_expert",
            password="test-password",
            role=User.Role.ANALYST,
        )
        profile = AnalystProfile.objects.get(user=self.analyst)
        profile.display_name = "Sport Profit Expert"
        profile.is_public = True
        profile.save(update_fields=["display_name", "is_public", "updated_at"])

        self.football = Sport.objects.create(
            external_id=1,
            code="football",
            name="Football",
            name_ru="Футбол",
        )
        self.hockey = Sport.objects.create(
            external_id=2,
            code="hockey",
            name="Hockey",
            name_ru="Хоккей",
        )
        self.football_match = Match.objects.create(
            external_id=101,
            sport=self.football,
            sync_scope=Match.SyncScope.PREMATCH,
        )
        self.hockey_match = Match.objects.create(
            external_id=102,
            sport=self.hockey,
            sync_scope=Match.SyncScope.PREMATCH,
        )

    def _moment(self, year=2026, month=8, day=10):
        value = datetime(year, month, day, 12, 0, 0)
        if timezone.is_aware(timezone.now()):
            return timezone.make_aware(value, timezone.get_current_timezone())
        return value

    def _coupon(self, state, stake, payout, matches):
        settled_at = self._moment()
        coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=state,
            total_stake=Decimal(str(stake)),
            possible_payout=Decimal(str(payout)),
            published_at=settled_at,
            settled_at=settled_at,
        )
        per_item_stake = Decimal(str(stake)) / Decimal(len(matches))
        for index, match in enumerate(matches, start=1):
            Prediction.objects.create(
                coupon=coupon,
                match=match,
                market="winner",
                selection=f"pick-{index}",
                coefficient=Decimal("2.00"),
                stake=per_item_stake,
            )
        return coupon

    def test_monthly_snapshot_persists_sport_split_without_double_counting_money(self):
        self._coupon(
            PredictionCoupon.StateStatus.WIN,
            100,
            200,
            [self.football_match, self.hockey_match],
        )
        self._coupon(
            PredictionCoupon.StateStatus.LOSE,
            100,
            200,
            [self.football_match],
        )

        stat = CapperMonthlyStat.objects.get(
            analyst=self.analyst,
            month=date(2026, 8, 1),
        )
        football = stat.sports_data["football"]
        hockey = stat.sports_data["hockey"]

        self.assertEqual(football["predictions_count"], 2)
        self.assertEqual(football["wins_count"], 1)
        self.assertEqual(football["losses_count"], 1)
        self.assertEqual(football["allocated_stake"], "150.00")
        self.assertEqual(football["allocated_profit"], "-50.00")

        self.assertEqual(hockey["predictions_count"], 1)
        self.assertEqual(hockey["wins_count"], 1)
        self.assertEqual(hockey["allocated_stake"], "50.00")
        self.assertEqual(hockey["allocated_profit"], "50.00")

        allocated_stake = Decimal(football["allocated_stake"]) + Decimal(hockey["allocated_stake"])
        allocated_profit = Decimal(football["allocated_profit"]) + Decimal(hockey["allocated_profit"])
        self.assertEqual(allocated_stake, stat.total_stake)
        self.assertEqual(allocated_profit, stat.total_profit)

    def test_public_profile_renders_database_backed_sport_period_filter(self):
        self._coupon(
            PredictionCoupon.StateStatus.WIN,
            100,
            190,
            [self.football_match],
        )

        response = self.client.get(
            reverse("front:expert_profile", kwargs={"username": self.analyst.username})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Прибыль по видам спорта за")
        self.assertContains(response, "все время")
        self.assertContains(response, "август 2026")
        self.assertContains(response, "Футбол")
        self.assertContains(response, "front/css/main.css")
        self.assertContains(response, "expert-sport-profit.js")
        self.assertContains(response, 'data-sport-profit-period="2026-08"')
