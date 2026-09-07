from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from back.models import WebsiteSettings
from tournaments.models import Tournament, TournamentParticipant
from tournaments.services.leaderboard import finalize_tournament_results
from wallets.models import RealBalanceTransaction

from .models import AnalystPaidPlan, AnalystProfile, ReferralVisit, User
from .paid_predictions import subscribe_to_paid_predictions


TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(STORAGES=TEST_STORAGES)
class ReferralBillingTests(TestCase):
    def setUp(self):
        self.settings = WebsiteSettings.load()
        self.referrer = User.objects.create_user(
            username="billing-referrer",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.target_analyst = User.objects.create_user(
            username="billing-target",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        profile = AnalystProfile.objects.get(user=self.target_analyst)
        profile.paid_predictions_enabled = True
        profile.paid_predictions_price = Decimal("1000.00")
        profile.save(update_fields=["paid_predictions_enabled", "paid_predictions_price", "updated_at"])

    def _registered_referral(self, referrer, visitor):
        return ReferralVisit.objects.create(
            referrer=referrer,
            visitor=visitor,
            session_key=f"billing-ref-{referrer.pk}-{visitor.pk}",
            registered_at=timezone.now(),
        )

    def test_regular_referrer_does_not_receive_money(self):
        self.settings.referral_subscription_percent = Decimal("10.00")
        self.settings.save(update_fields=["referral_subscription_percent", "updated_at"])
        regular_referrer = User.objects.create_user(
            username="regular-referrer",
            password="safe-test-password",
            role=User.Role.READER,
        )
        buyer = User.objects.create_user(
            username="regular-ref-buyer",
            password="safe-test-password",
            role=User.Role.READER,
        )
        self._registered_referral(regular_referrer, buyer)

        subscribe_to_paid_predictions(buyer, self.target_analyst)

        self.assertFalse(RealBalanceTransaction.objects.filter(user=regular_referrer).exists())

    def test_capper_referrer_receives_subscription_income(self):
        self.settings.referral_subscription_percent = Decimal("10.00")
        self.settings.save(update_fields=["referral_subscription_percent", "updated_at"])
        buyer = User.objects.create_user(
            username="capper-ref-buyer",
            password="safe-test-password",
            role=User.Role.READER,
        )
        self._registered_referral(self.referrer, buyer)

        subscribe_to_paid_predictions(buyer, self.target_analyst)

        self.referrer.real_balance.refresh_from_db()
        self.assertEqual(self.referrer.real_balance.balance, Decimal("100.00"))
        self.assertTrue(
            RealBalanceTransaction.objects.filter(
                user=self.referrer,
                kind=RealBalanceTransaction.Kind.REFERRAL_SUBSCRIPTION,
                amount=Decimal("100.00"),
            ).exists()
        )

    def test_capper_referrer_receives_tournament_prize_income(self):
        self.settings.referral_tournament_percent = Decimal("20.00")
        self.settings.save(update_fields=["referral_tournament_percent", "updated_at"])
        participant_user = User.objects.create_user(
            username="referred-tournament-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self._registered_referral(self.referrer, participant_user)
        tournament = Tournament.objects.create(
            title="Referral Prize Cup",
            status=Tournament.Status.PUBLISHED,
            starts_at=timezone.now() - timedelta(days=5),
            ends_at=timezone.now() - timedelta(days=1),
            prize_first=Decimal("1000.00"),
        )
        TournamentParticipant.objects.create(tournament=tournament, user=participant_user)

        finalize_tournament_results(tournament)

        self.referrer.real_balance.refresh_from_db()
        self.assertEqual(self.referrer.real_balance.balance, Decimal("200.00"))
        self.assertTrue(
            RealBalanceTransaction.objects.filter(
                user=self.referrer,
                kind=RealBalanceTransaction.Kind.REFERRAL_TOURNAMENT,
                amount=Decimal("200.00"),
            ).exists()
        )

    def test_capper_referrer_receives_balance_top_up_income(self):
        self.settings.referral_balance_topup_percent = Decimal("5.00")
        self.settings.save(update_fields=["referral_balance_topup_percent", "updated_at"])
        referred_capper = User.objects.create_user(
            username="referred-topup-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self._registered_referral(self.referrer, referred_capper)
        self.client.force_login(referred_capper)

        response = self.client.post(reverse("wallets:top_up"))

        self.assertEqual(response.status_code, 302)
        self.referrer.real_balance.refresh_from_db()
        self.assertEqual(self.referrer.real_balance.balance, Decimal("500.00"))
        self.assertTrue(
            RealBalanceTransaction.objects.filter(
                user=self.referrer,
                kind=RealBalanceTransaction.Kind.REFERRAL_BALANCE_TOP_UP,
                amount=Decimal("500.00"),
            ).exists()
        )

    def test_platform_fee_is_deducted_by_paid_plan_duration(self):
        fee_by_duration = {
            1: Decimal("10.00"),
            7: Decimal("20.00"),
            30: Decimal("30.00"),
            90: Decimal("40.00"),
            180: Decimal("50.00"),
        }
        self.settings.platform_fee_1_day_percent = fee_by_duration[1]
        self.settings.platform_fee_7_days_percent = fee_by_duration[7]
        self.settings.platform_fee_30_days_percent = fee_by_duration[30]
        self.settings.platform_fee_90_days_percent = fee_by_duration[90]
        self.settings.platform_fee_180_days_percent = fee_by_duration[180]
        self.settings.save(
            update_fields=[
                "platform_fee_1_day_percent",
                "platform_fee_7_days_percent",
                "platform_fee_30_days_percent",
                "platform_fee_90_days_percent",
                "platform_fee_180_days_percent",
                "updated_at",
            ]
        )

        for order, duration_days in enumerate(fee_by_duration, start=1):
            plan = AnalystPaidPlan.objects.create(
                analyst=self.target_analyst,
                title=f"{duration_days} days",
                duration_days=duration_days,
                price=Decimal("1000.00"),
                order=order,
            )
            buyer = User.objects.create_user(
                username=f"fee-buyer-{duration_days}",
                password="safe-test-password",
                role=User.Role.READER,
            )

            subscribe_to_paid_predictions(buyer, self.target_analyst, plan)

            expected_income = Decimal("1000.00") - (Decimal("1000.00") * fee_by_duration[duration_days] / 100)
            self.assertTrue(
                RealBalanceTransaction.objects.filter(
                    user=self.target_analyst,
                    kind=RealBalanceTransaction.Kind.SUBSCRIPTION_INCOME,
                    amount=expected_income,
                    note=f"Подписка @{buyer.username}: {plan.title}",
                ).exists()
            )
