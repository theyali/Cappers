from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import AnalystProfile, CapperMonthlyStat, User
from .presence import UserPresence, presence_payload, touch_user_presence
from .sport_stats import catalog_sport_stats, sport_profit_periods


class UserPresenceTests(TestCase):
    def test_presence_payload_formats_minutes_and_online_state(self):
        user = User.objects.create_user(username="presence-reader", password="test-password")
        now = timezone.now()

        UserPresence.objects.create(
            user=user,
            last_seen_at=now - timedelta(minutes=44),
        )
        offline = presence_payload(user, now=now)
        self.assertFalse(offline["is_online"])
        self.assertEqual(offline["label"], "Был(а) 44 мин назад")

        touch_user_presence(user, now=now, force=True)
        online = presence_payload(user, now=now)
        self.assertTrue(online["is_online"])
        self.assertEqual(online["label"], "В сети")

    def test_reader_public_profile_renders_last_seen(self):
        user = User.objects.create_user(username="public-reader", password="test-password")
        UserPresence.objects.create(
            user=user,
            last_seen_at=timezone.now() - timedelta(minutes=44),
        )

        response = self.client.get(
            reverse("cabinet:user_profile", kwargs={"username": user.username})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Был(а) 44 мин назад")
        self.assertContains(response, "public-presence-status")

    def test_expert_public_profile_exposes_online_presence(self):
        analyst = User.objects.create_user(
            username="public-online-expert",
            password="test-password",
            role=User.Role.ANALYST,
        )
        profile = AnalystProfile.objects.get(user=analyst)
        profile.is_public = True
        profile.save(update_fields=["is_public", "updated_at"])
        UserPresence.objects.create(user=analyst, last_seen_at=timezone.now())

        response = self.client.get(
            reverse("front:expert_profile", kwargs={"username": analyst.username})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-public-presence-source')
        self.assertContains(response, 'data-online="1"')
        self.assertContains(response, 'data-label="В сети"')


class SportStatsTests(TestCase):
    def setUp(self):
        self.analyst = User.objects.create_user(
            username="sport-stat-expert",
            password="test-password",
            role=User.Role.ANALYST,
        )

    def _monthly_row(self):
        return CapperMonthlyStat.objects.create(
            analyst=self.analyst,
            month=date(2026, 8, 1),
            bets_count=3,
            wins_count=2,
            losses_count=1,
            refunds_count=0,
            total_stake=Decimal("300.00"),
            total_profit=Decimal("60.00"),
            flat_profit_percent=Decimal("20.00"),
            roi=Decimal("20.00"),
            avg_coefficient=Decimal("1.90"),
            hit_rate=Decimal("66.67"),
            sports_data={
                "football": {
                    "code": "football",
                    "name": "Футбол",
                    "predictions_count": 2,
                    "wins_count": 2,
                    "losses_count": 0,
                    "refunds_count": 0,
                    "allocated_stake": "200.00",
                    "allocated_profit": "80.00",
                    "flat_units": "0.80",
                    "weight": "2.00",
                    "coefficient_sum": "3.80",
                },
                "hockey": {
                    "code": "hockey",
                    "name": "Хоккей",
                    "predictions_count": 1,
                    "wins_count": 0,
                    "losses_count": 1,
                    "refunds_count": 0,
                    "allocated_stake": "100.00",
                    "allocated_profit": "-20.00",
                    "flat_units": "-0.20",
                    "weight": "1.00",
                    "coefficient_sum": "1.90",
                },
            },
        )

    def test_period_contains_all_sports_and_individual_sports(self):
        row = self._monthly_row()
        periods, options = sport_profit_periods([row])

        codes = [item["code"] for item in periods["all"]["rows"]]
        self.assertEqual(codes[0], "all")
        self.assertIn("football", codes)
        self.assertIn("hockey", codes)
        self.assertEqual(periods["all"]["rows"][0]["name"], "Все виды спорта")
        self.assertEqual(periods["all"]["rows"][0]["predictions_count"], 3)
        self.assertEqual(periods["all"]["rows"][0]["roi"], 20.0)
        self.assertEqual(options[0]["key"], "all")

    def test_catalog_stats_are_loaded_from_persisted_monthly_data(self):
        self._monthly_row()
        stats, options = catalog_sport_stats([self.analyst.id])

        self.assertEqual(stats[self.analyst.id]["all"]["predictions_count"], 3)
        self.assertEqual(stats[self.analyst.id]["football"]["roi"], 40.0)
        self.assertEqual(stats[self.analyst.id]["hockey"]["roi"], -20.0)
        self.assertEqual(
            [item["code"] for item in options],
            ["all", "football", "hockey"],
        )

    def test_cappers_catalog_embeds_sport_specific_stats(self):
        self._monthly_row()
        response = self.client.get(reverse("front:cappers_stats"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-capper-sport-source="football"')
        self.assertContains(response, "Все виды спорта")
        self.assertContains(response, "cappers-sport-filter.js")
