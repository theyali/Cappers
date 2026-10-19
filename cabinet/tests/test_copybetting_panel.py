import csv
import io
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cabinet.models import User
from cabinet.services.copybetting import build_copybetting_context
from game.models import PredictionCoupon
from wallets.models import CopiedBet, CopyBettingSubscription


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class CopybettingPanelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = User.objects.create_user(username="copy-author", role=User.Role.ANALYST)
        cls.other = User.objects.create_user(username="copy-other", role=User.Role.ANALYST)
        cls.people = []
        for number in range(10):
            reader = User.objects.create_user(username=f"reader-{number:02d}")
            sub = CopyBettingSubscription.objects.create(
                user=reader, analyst=cls.author, status="active" if number < 6 else "stopped",
                bank_amount=Decimal("56789"), stake_percent=Decimal("10"), max_single_stake=Decimal("500"),
                total_profit=Decimal("475") if number != 2 else Decimal("-500"),
                stopped_at=timezone.now() if number >= 6 else None,
            )
            cls.people.append(sub)
        cls.foreign_reader = User.objects.create_user(username="foreign-reader")
        cls.foreign = CopyBettingSubscription.objects.create(
            user=cls.foreign_reader, analyst=cls.other, bank_amount=1000, stake_percent=10,
        )
        cls.coupon = PredictionCoupon.objects.create(
            author=cls.author, published_status="published", state_status="win", total_stake=100,
            possible_payout=195, headline="Наш исходный купон",
        )
        for sub in cls.people[:5]:
            CopiedBet.objects.create(subscription=sub, user=sub.user, analyst=cls.author,
                                     source_coupon=cls.coupon, state_status="win", stake=500,
                                     possible_payout=975, profit=475)

    def setUp(self):
        self.client.force_login(self.author)

    def get(self, **params):
        return self.client.get(reverse("cabinet:copybetting_audience"), params)

    def test_access_is_private_and_readers_keep_their_existing_controls(self):
        self.client.logout()
        self.assertEqual(self.get().status_code, 302)
        self.client.force_login(self.people[0].user)
        self.assertEqual(self.get().status_code, 403)
        response = self.client.get(reverse("cabinet:profile"), {"tab": "copybetting"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "copybetting-reader")
        self.assertContains(response, reverse("wallets:copybetting_pause", args=[self.people[0].pk]))
        self.assertContains(response, 'data-copy-role="reader"')

    def test_summary_and_filters_do_not_expose_another_analysts_audience_or_wallets(self):
        context = build_copybetting_context(self.author, {})
        self.assertEqual(context["copybetting_audience_total_count"], 10)
        self.assertEqual(context["copybetting_audience_active_count"], 6)
        response = self.get(copy_q="@reader-02")
        html = response.json()["html"]
        self.assertIn("@reader-02", html)
        self.assertNotIn("foreign-reader", html)
        self.assertNotIn("56789", html)
        self.assertNotIn("56 789", html)
        self.assertIn("500", html)
        self.assertIn("−500", html)
        self.assertIn("no-store", response["Cache-Control"])

    def test_filters_are_applied_before_pagination_and_keep_stopped_history(self):
        first = build_copybetting_context(self.author, {})
        second = build_copybetting_context(self.author, {"copy_page": 2})
        self.assertEqual(len(first["copybetting_people"]), 8)
        self.assertEqual(len(second["copybetting_people"]), 2)
        ids = [p["id"] for p in first["copybetting_people"] + second["copybetting_people"]]
        self.assertEqual(len(set(ids)), 10)
        stopped = build_copybetting_context(self.author, {"copy_status": "stopped"})
        self.assertEqual(stopped["copybetting_filtered_count"], 4)
        self.assertTrue(all(person["stopped_at"] for person in stopped["copybetting_people"]))
        query = build_copybetting_context(self.author, {"copy_q": "reader-09"})
        self.assertEqual(query["copybetting_filtered_count"], 1)
        self.assertEqual(query["copybetting_people"][0]["username"], "reader-09")

    def test_period_and_invalid_page_are_safe(self):
        CopyBettingSubscription.objects.filter(pk=self.people[0].pk).update(started_at=timezone.now() - timedelta(days=40))
        context = build_copybetting_context(self.author, {"copy_period": "30", "copy_page": 999})
        self.assertEqual(context["copybetting_filtered_count"], 9)
        self.assertEqual(len(context["copybetting_people"]), 1)
        self.assertEqual(self.get(copy_status="invalid", copy_period="invalid", copy_page="invalid").status_code, 200)
        for invalid_id in ("²", "9" * 5000, "-1"):
            self.assertEqual(self.get(copy_user=invalid_id).status_code, 200)

    def test_copied_bets_are_grouped_by_coupon_and_can_be_scoped_to_one_person(self):
        context = build_copybetting_context(self.author, {"copy_view": "bets"})
        self.assertEqual(len(context["copybetting_bets"]), 1)
        bet = context["copybetting_bets"][0]
        self.assertEqual(bet["count"], 5)
        self.assertEqual(len(bet["people"]), 3)
        self.assertEqual(bet["extra"], 2)
        self.assertEqual(bet["amount"], "2 500")
        self.assertEqual(bet["result"], "Прошла")
        self.assertEqual(bet["coefficient"], "1,95")
        self.assertEqual(self.get(copy_view="bets").status_code, 200)
        selected = build_copybetting_context(self.author, {"copy_view": "bets", "copy_user": self.people[0].user_id})
        self.assertEqual(selected["copybetting_bets"][0]["count"], 1)
        self.assertEqual(selected["copybetting_selected"]["id"], self.people[0].user_id)
        foreign = build_copybetting_context(self.author, {"copy_view": "bets", "copy_user": self.foreign_reader.pk})
        self.assertEqual(foreign["copybetting_bets"], [])
        self.assertIsNone(foreign["copybetting_selected"])

    def test_csv_exports_all_filtered_rows_with_safe_usernames(self):
        self.people[0].user.username = "=1+1"
        self.people[0].user.save(update_fields=["username"])
        response = self.get(export="csv")
        rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
        self.assertEqual(len(rows), 11)
        self.assertIn("'=1+1", [row[0] for row in rows])
        self.assertNotIn("foreign-reader", response.content.decode())
        self.assertNotIn("56789", response.content.decode())
        filtered = self.get(export="csv", copy_status="stopped")
        self.assertEqual(len(list(csv.reader(io.StringIO(filtered.content.decode("utf-8-sig"))))), 5)

    def test_empty_state_has_real_zeroes_and_the_single_shared_help_dialog(self):
        self.client.force_login(self.other)
        CopyBettingSubscription.objects.filter(analyst=self.other).delete()
        response = self.client.get(reverse("cabinet:profile"), {"tab": "copybetting"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Вас пока никто не копирует")
        self.assertContains(response, 'id="copybetting-how-modal"', count=1)
        self.assertContains(response, "copybetting-sheet-handle")
        self.assertContains(response, "Влияет ли копирование на мой индекс доверия?")
        self.assertContains(response, "Запрет со стороны автора появится позже")
        html = self.get().json()["html"]
        self.assertIn("Вас пока никто не копирует", html)
        self.assertNotIn("maxbet_77", html)
        self.assertNotIn("38 420", html)
