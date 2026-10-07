from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from back.models import WebsiteSettings
from cabinet.models import User
from cabinet.paid_predictions import paid_subscription_capper_income
from game.models import PredictionCoupon
from tournaments.models import Tournament, TournamentCoupon, TournamentParticipant
from tournaments.services.eligibility import check_tournament_eligibility
from tournaments.services.leaderboard import finalize_tournament_results
from wallets.models import RealBalanceTransaction
from wallets.services import (
    InsufficientBalance,
    approve_real_withdrawal,
    cancel_real_withdrawal,
    credit_real_balance,
    release_held_real_income,
    request_real_withdrawal,
)


TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


class RealBalanceTestCase(TestCase):
    def setUp(self):
        self.analyst = User.objects.create_user(
            username="real-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )

    def _balance(self):
        self.analyst.real_balance.refresh_from_db()
        return self.analyst.real_balance

    def _fund(self, amount):
        balance = self._balance()
        balance.balance = Decimal(amount)
        balance.save(update_fields=["balance", "updated_at"])

    def _withdrawal(self):
        return RealBalanceTransaction.objects.get(
            user=self.analyst,
            kind=RealBalanceTransaction.Kind.WITHDRAWAL_REQUEST,
        )


class IncomeHoldTests(RealBalanceTestCase):
    def _subscription_income(self, amount="300.00", related_obj=None):
        credit_real_balance(
            self.analyst,
            Decimal(amount),
            RealBalanceTransaction.Kind.SUBSCRIPTION_INCOME,
            related_obj=related_obj,
        )

    def test_subscription_income_is_held_until_the_hold_ends(self):
        self._subscription_income("600.00")

        balance = self._balance()
        self.assertEqual(balance.balance, Decimal("0.00"))
        self.assertEqual(balance.held, Decimal("600.00"))
        held = RealBalanceTransaction.objects.get(user=self.analyst)
        self.assertEqual(held.status, RealBalanceTransaction.Status.HELD)
        self.assertAlmostEqual(held.available_at, timezone.now() + timedelta(days=7), delta=timedelta(minutes=1))
        with self.assertRaises(InsufficientBalance):
            request_real_withdrawal(self.analyst, Decimal("600.00"), payout_details="СБП +79990000000")

        self.assertEqual(release_held_real_income(), 0)

        RealBalanceTransaction.objects.filter(pk=held.pk).update(available_at=timezone.now())
        self.assertEqual(release_held_real_income(), 1)

        balance = self._balance()
        self.assertEqual(balance.balance, Decimal("600.00"))
        self.assertEqual(balance.held, Decimal("0.00"))
        held.refresh_from_db()
        self.assertEqual(held.status, RealBalanceTransaction.Status.COMPLETED)
        self.assertEqual(held.balance_after, Decimal("600.00"))
        self.assertEqual(release_held_real_income(), 0)

    def test_zero_hold_days_credit_at_once(self):
        settings = WebsiteSettings.load()
        settings.income_hold_days = 0
        settings.save(update_fields=["income_hold_days"])

        self._subscription_income()

        self.assertEqual(self._balance().balance, Decimal("300.00"))

    def test_tournament_prize_is_not_held(self):
        credit_real_balance(self.analyst, Decimal("1000.00"), RealBalanceTransaction.Kind.TOURNAMENT_PRIZE)

        self.assertEqual(self._balance().balance, Decimal("1000.00"))


class WithdrawalTestCase(RealBalanceTestCase):
    def setUp(self):
        super().setUp()
        self._fund("2000.00")
        self.admin_user = User.objects.create_superuser(
            username="real-admin",
            password="safe-test-password",
            email="real-admin@example.com",
        )


class WithdrawalRequestTests(WithdrawalTestCase):
    def test_request_stores_payout_details(self):
        request_real_withdrawal(self.analyst, Decimal("700.00"), payout_details="  СБП +79990000000 ")

        withdrawal = self._withdrawal()
        self.assertEqual(withdrawal.status, RealBalanceTransaction.Status.PENDING)
        self.assertEqual(withdrawal.payout_details, "СБП +79990000000")
        self.assertEqual(self._balance().balance, Decimal("1300.00"))

    def test_minimum_amount_and_payout_details_are_required(self):
        with self.assertRaisesMessage(ValidationError, "Минимальная сумма вывода — 500 ₽."):
            request_real_withdrawal(self.analyst, Decimal("499.99"), payout_details="СБП +79990000000")
        with self.assertRaisesMessage(ValidationError, "Укажите реквизиты"):
            request_real_withdrawal(self.analyst, Decimal("700.00"), payout_details="   ")

        self.assertFalse(RealBalanceTransaction.objects.filter(user=self.analyst).exists())

    def test_only_one_open_request(self):
        request_real_withdrawal(self.analyst, Decimal("700.00"), payout_details="СБП +79990000000")

        with self.assertRaisesMessage(ValidationError, "уже есть заявка"):
            request_real_withdrawal(self.analyst, Decimal("700.00"), payout_details="СБП +79990000000")

        cancel_real_withdrawal(self._withdrawal(), processed_by=self.admin_user)
        request_real_withdrawal(self.analyst, Decimal("700.00"), payout_details="СБП +79990000000")

    def test_approval_requires_payout_number_and_records_who_approved(self):
        request_real_withdrawal(self.analyst, Decimal("700.00"), payout_details="СБП +79990000000")

        with self.assertRaisesMessage(ValidationError, "Укажите номер выплаты"):
            approve_real_withdrawal(self._withdrawal(), processed_by=self.admin_user)

        approve_real_withdrawal(self._withdrawal(), payout_reference="SBP-123", processed_by=self.admin_user)

        withdrawal = self._withdrawal()
        self.assertEqual(withdrawal.status, RealBalanceTransaction.Status.COMPLETED)
        self.assertEqual(withdrawal.payout_reference, "SBP-123")
        self.assertEqual(withdrawal.processed_by, self.admin_user)
        self.assertIsNotNone(withdrawal.processed_at)

    def test_cancel_records_who_canceled(self):
        request_real_withdrawal(self.analyst, Decimal("700.00"), payout_details="СБП +79990000000")

        cancel_real_withdrawal(self._withdrawal(), processed_by=self.admin_user)

        withdrawal = self._withdrawal()
        self.assertEqual(withdrawal.processed_by, self.admin_user)
        self.assertEqual(self._balance().balance, Decimal("2000.00"))


@override_settings(STORAGES=TEST_STORAGES)
class WithdrawalPagesTests(WithdrawalTestCase):
    def test_withdraw_form_sends_payout_details(self):
        self.client.force_login(self.analyst)

        response = self.client.post(
            reverse("wallets:real_action"),
            {"action": "withdraw", "amount": "700", "payout_details": "Карта 2200 0000 0000 0000"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._withdrawal().payout_details, "Карта 2200 0000 0000 0000")

    def test_admin_approves_after_entering_payout_number(self):
        request_real_withdrawal(self.analyst, Decimal("700.00"), payout_details="СБП +79990000000")
        withdrawal = self._withdrawal()
        self.client.force_login(self.admin_user)
        changelist = reverse("admin:wallets_realbalancetransaction_changelist")
        action = {"action": "approve_withdrawals", "_selected_action": [withdrawal.pk]}

        response = self.client.post(changelist, action, follow=True)
        self.assertContains(response, "Укажите номер выплаты")

        change_page = self.client.get(reverse("admin:wallets_realbalancetransaction_change", args=[withdrawal.pk]))
        self.assertContains(change_page, 'name="payout_reference"')
        RealBalanceTransaction.objects.filter(pk=withdrawal.pk).update(payout_reference="SBP-777")

        response = self.client.post(changelist, action, follow=True)
        self.assertContains(response, "Подтверждено заявок: 1.")
        withdrawal.refresh_from_db()
        self.assertEqual(withdrawal.status, RealBalanceTransaction.Status.COMPLETED)
        self.assertEqual(withdrawal.processed_by, self.admin_user)

    def test_top_up_page_shows_held_income(self):
        credit_real_balance(self.analyst, Decimal("300.00"), RealBalanceTransaction.Kind.SUBSCRIPTION_INCOME)
        self.client.force_login(self.analyst)

        response = self.client.get(reverse("wallets:top_up"))

        self.assertContains(response, "В холде: 300 ₽")
        self.assertContains(response, 'name="payout_details"')


class PlatformFeeTests(TestCase):
    def test_non_standard_plan_length_pays_the_fee_of_the_shorter_plan(self):
        settings = WebsiteSettings.load()
        settings.platform_fee_1_day_percent = Decimal("30")
        settings.platform_fee_7_days_percent = Decimal("20")
        settings.platform_fee_180_days_percent = Decimal("10")
        settings.save()

        self.assertEqual(paid_subscription_capper_income(Decimal("1000"), 14), Decimal("800.00"))
        self.assertEqual(paid_subscription_capper_income(Decimal("1000"), 3), Decimal("700.00"))
        self.assertEqual(paid_subscription_capper_income(Decimal("1000"), 365), Decimal("900.00"))
        self.assertEqual(paid_subscription_capper_income(Decimal("1000"), 7), Decimal("800.00"))


class MoneyTournamentReaderTests(TestCase):
    def setUp(self):
        self.reader = User.objects.create_user(
            username="prize-reader",
            password="safe-test-password",
            role=User.Role.READER,
        )
        self.tournament = Tournament.objects.create(
            title="Open Cup",
            status=Tournament.Status.PUBLISHED,
            analysts_only=False,
            starts_at=timezone.now() - timedelta(days=3),
            ends_at=timezone.now() - timedelta(minutes=1),
            prize_first=Decimal("1000.00"),
        )

    def test_reader_cannot_join_tournament_with_money_prizes(self):
        eligibility = check_tournament_eligibility(self.reader, self.tournament)

        self.assertFalse(eligibility["allowed"])
        self.assertIn("В турнирах с денежными призами участвуют только капперы.", eligibility["reasons"])

    def test_reader_can_join_tournament_without_money_prizes(self):
        Tournament.objects.filter(pk=self.tournament.pk).update(prize_first=0)
        self.tournament.refresh_from_db()

        self.assertTrue(check_tournament_eligibility(self.reader, self.tournament)["hard_allowed"])

    def test_reader_in_money_place_stops_finalization_with_a_clear_error(self):
        participant = TournamentParticipant.objects.create(tournament=self.tournament, user=self.reader)
        coupon = PredictionCoupon.objects.create(
            author=self.reader,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=PredictionCoupon.StateStatus.WIN,
            total_stake=Decimal("100"),
            possible_payout=Decimal("200"),
            confidence=80,
            published_at=timezone.now() - timedelta(days=2),
        )
        TournamentCoupon.objects.create(tournament=self.tournament, participant=participant, coupon=coupon)

        with self.assertRaisesMessage(ValidationError, "@prize-reader"):
            finalize_tournament_results(self.tournament)

        self.tournament.refresh_from_db()
        self.assertIsNone(self.tournament.finalized_at)
