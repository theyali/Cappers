from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from wallets.models import RealBalanceTransaction
from wallets.services import credit_real_balance

from .models import AnalystPaidSubscription, User


class AnalystEarningsTests(TestCase):
    def setUp(self):
        self.analyst = User.objects.create_user(
            username="earnings-analyst",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.subscriber = User.objects.create_user(
            username="earnings-reader",
            password="safe-test-password",
            role=User.Role.READER,
        )
        AnalystPaidSubscription.objects.create(
            subscriber=self.subscriber,
            analyst=self.analyst,
            price=Decimal("500.00"),
            starts_at=timezone.now(),
            expires_at=timezone.now() + timedelta(days=30),
        )

    def _income(self, amount: str, kind: str, *, days_ago: int, note: str):
        credit_real_balance(self.analyst, Decimal(amount), kind, note=note)
        transaction = RealBalanceTransaction.objects.filter(
            user=self.analyst,
            kind=kind,
            note=note,
        ).latest("id")
        RealBalanceTransaction.objects.filter(pk=transaction.pk).update(
            created_at=timezone.now() - timedelta(days=days_ago)
        )
        return transaction

    def test_earnings_page_splits_income_by_period_and_source(self):
        self._income(
            "500.00",
            RealBalanceTransaction.Kind.SUBSCRIPTION_INCOME,
            days_ago=2,
            note="week subscription",
        )
        self._income(
            "1000.00",
            RealBalanceTransaction.Kind.TOURNAMENT_PRIZE,
            days_ago=20,
            note="month tournament",
        )
        self._income(
            "300.00",
            RealBalanceTransaction.Kind.SUBSCRIPTION_INCOME,
            days_ago=70,
            note="quarter subscription",
        )
        self._income(
            "5000.00",
            RealBalanceTransaction.Kind.ADJUSTMENT,
            days_ago=1,
            note="not earned income",
        )

        self.client.force_login(self.analyst)
        response = self.client.get(reverse("cabinet:profile_earnings"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_tab"], "earnings")
        self.assertEqual(response.context["active_paid_subscribers"], 1)
        self.assertEqual(response.context["earnings_all_time"]["total"], Decimal("1800.00"))
        self.assertEqual(
            response.context["earnings_all_time"]["subscription_income"],
            Decimal("800.00"),
        )
        self.assertEqual(
            response.context["earnings_all_time"]["tournament_income"],
            Decimal("1000.00"),
        )

        week, month, quarter = response.context["earnings_periods"]
        self.assertEqual(week["total"], Decimal("500.00"))
        self.assertEqual(week["subscription_purchases"], 1)
        self.assertEqual(month["total"], Decimal("1500.00"))
        self.assertEqual(month["tournament_income"], Decimal("1000.00"))
        self.assertEqual(quarter["total"], Decimal("1800.00"))
        self.assertContains(response, "Доходы")
        self.assertContains(response, "Рефералы")

    def test_reader_cannot_open_analyst_earnings_page(self):
        self.client.force_login(self.subscriber)

        response = self.client.get(reverse("cabinet:profile_earnings"))

        self.assertRedirects(response, reverse("cabinet:profile"))
