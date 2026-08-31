from decimal import Decimal

from django.test import SimpleTestCase
from django.urls import reverse

from .capper_table_service import _sport_metrics


class CapperTableRoutingTests(SimpleTestCase):
    def test_clean_ranking_urls(self):
        self.assertEqual(reverse("front:cappers_table"), "/cappers-table/")
        self.assertEqual(
            reverse("front:cappers_table_group", kwargs={"group": "vip"}),
            "/cappers-table/vip/",
        )
        self.assertEqual(
            reverse("front:cappers_table_group", kwargs={"group": "paid"}),
            "/cappers-table/paid/",
        )
        self.assertEqual(
            reverse(
                "front:cappers_table_period",
                kwargs={"group": "popular", "period": "2026-08"},
            ),
            "/cappers-table/popular/2026-08/",
        )
        self.assertEqual(
            reverse(
                "front:cappers_table_sport",
                kwargs={
                    "group": "vip",
                    "period": "2026-08",
                    "sport_code": "football",
                },
            ),
            "/cappers-table/vip/2026-08/football/",
        )

    def test_sport_snapshot_has_own_metrics(self):
        metrics = _sport_metrics(
            {
                "predictions_count": 10,
                "wins_count": 6,
                "losses_count": 3,
                "refunds_count": 1,
                "allocated_stake": "1000.00",
                "allocated_profit": "125.00",
                "flat_units": "1.50",
                "weight": "10.00",
                "coefficient_sum": "20.50",
            }
        )

        self.assertIsNotNone(metrics)
        self.assertEqual(metrics["bets"], 10)
        self.assertEqual(metrics["wins"], 6)
        self.assertEqual(metrics["losses"], 3)
        self.assertEqual(metrics["refunds"], 1)
        self.assertEqual(metrics["flat_profit_percent"], Decimal("15.0"))
        self.assertEqual(metrics["roi"], Decimal("12.5"))
        self.assertEqual(metrics["avg_coefficient"], Decimal("2.05"))
        self.assertEqual(metrics["hit_rate"], Decimal("60.0"))
