from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from cabinet.models import AnalystProfile, CapperMonthlyStat, User

from .expert_ranking import expert_ranking_score


class ExpertRankingScoreTests(SimpleTestCase):
    @staticmethod
    def _profile(*, trust_index, roi, settled_count):
        return SimpleNamespace(
            trust_index=Decimal(str(trust_index)),
            author_roi=Decimal(str(roi)),
            roi_settled_count=settled_count,
            settled_count=settled_count,
        )

    def test_higher_trust_index_beats_extreme_roi_with_lower_trust(self):
        trusted = self._profile(trust_index="8.0", roi="-100", settled_count=100)
        lucky = self._profile(trust_index="7.9", roi="1000", settled_count=3)

        self.assertGreater(
            expert_ranking_score(trusted),
            expert_ranking_score(lucky),
        )

    def test_equal_trust_index_uses_stabilized_roi_as_tie_breaker(self):
        stronger_roi = self._profile(trust_index="8.0", roi="18", settled_count=30)
        weaker_roi = self._profile(trust_index="8.0", roi="6", settled_count=30)

        self.assertGreater(
            expert_ranking_score(stronger_roi),
            expert_ranking_score(weaker_roi),
        )


class CapperTrustRankingIntegrationTests(TestCase):
    month = date(2026, 8, 1)

    @classmethod
    def setUpTestData(cls):
        cls.high_trust_user = User.objects.create_user(
            username="stable_trust",
            password="test-password",
            role=User.Role.ANALYST,
        )
        cls.high_roi_user = User.objects.create_user(
            username="high_roi_low_trust",
            password="test-password",
            role=User.Role.ANALYST,
        )

        high_trust_profile, _ = AnalystProfile.objects.get_or_create(
            user=cls.high_trust_user,
        )
        high_roi_profile, _ = AnalystProfile.objects.get_or_create(
            user=cls.high_roi_user,
        )
        AnalystProfile.objects.filter(pk=high_trust_profile.pk).update(
            is_public=True,
            trust_index=Decimal("8.8"),
        )
        AnalystProfile.objects.filter(pk=high_roi_profile.pk).update(
            is_public=True,
            trust_index=Decimal("4.2"),
        )

        CapperMonthlyStat.objects.create(
            analyst=cls.high_trust_user,
            month=cls.month,
            bets_count=20,
            wins_count=11,
            losses_count=8,
            refunds_count=1,
            total_stake=Decimal("2000"),
            total_profit=Decimal("60"),
            flat_profit_percent=Decimal("3.0"),
            roi=Decimal("3.0"),
            avg_coefficient=Decimal("1.90"),
            hit_rate=Decimal("55.0"),
        )
        CapperMonthlyStat.objects.create(
            analyst=cls.high_roi_user,
            month=cls.month,
            bets_count=3,
            wins_count=3,
            losses_count=0,
            refunds_count=0,
            total_stake=Decimal("300"),
            total_profit=Decimal("600"),
            flat_profit_percent=Decimal("200.0"),
            roi=Decimal("200.0"),
            avg_coefficient=Decimal("3.00"),
            hit_rate=Decimal("100.0"),
        )

    def test_month_table_returns_trust_first_order_and_visible_index_column(self):
        response = self.client.get(
            reverse(
                "front:cappers_table_period",
                kwargs={"group": "all", "period": "2026-08"},
            )
        )

        self.assertEqual(response.status_code, 200)
        usernames = [row["username"] for row in response.context["ranking_rows"]]
        self.assertEqual(
            usernames,
            [self.high_trust_user.username, self.high_roi_user.username],
        )
        self.assertContains(response, ">Индекс</th>", html=False)
        self.assertContains(response, 'title="Общий индекс"')
        self.assertContains(response, "capper-trust-badge")

    def test_cappers_statistics_and_table_share_canonical_trust_order(self):
        stats_response = self.client.get(
            reverse("front:cappers_stats"),
            {"roi_period": "all"},
        )
        table_response = self.client.get(reverse("front:cappers_table"))

        self.assertEqual(stats_response.status_code, 200)
        self.assertEqual(table_response.status_code, 200)

        expected_users = {
            self.high_trust_user.username,
            self.high_roi_user.username,
        }
        stats_order = [
            expert["username"]
            for expert in stats_response.context["experts"]
            if expert["username"] in expected_users
        ]
        table_order = [
            row["username"]
            for row in table_response.context["ranking_rows"]
            if row["username"] in expected_users
        ]

        self.assertEqual(
            stats_order,
            [self.high_trust_user.username, self.high_roi_user.username],
        )
        self.assertEqual(table_order, stats_order)

    def test_statistics_explains_trust_index_ranking(self):
        response = self.client.get(reverse("front:cappers_stats"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Рейтинг по индексу доверия")
        self.assertContains(
            response,
            "Индекс доверия учитывает ROI, просадку, стабильность, объем истории, средний коэффициент, активность и точность уверенности",
        )
