import json
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from cabinet.models import User
from game.models import Match, Prediction, PredictionCoupon
from game.services.settlement import settle_coupon
from wallets.models import BalanceTransaction
from wallets.services import charge_prediction_stake


TEST_STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


class CapperBalanceTests(TestCase):
    def setUp(self):
        self.analyst = User.objects.create_user(
            username="balance-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.match = Match.objects.create(
            external_id=881001,
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at=timezone.now() + timedelta(hours=1),
            raw_data={
                "teams": {
                    "home": {"name": {"ru": "Хозяева"}},
                    "away": {"name": {"ru": "Гости"}},
                },
                "league": {"name": {"ru": "Лига"}},
            },
        )

    def _payload(self, stake="500"):
        return {
            "stake": stake,
            "confidence": 70,
            "items": [
                {
                    "match_id": self.match.id,
                    "market": "winner",
                    "selection": "Хозяева",
                    "coefficient": "1.70",
                }
            ],
        }

    def test_new_analyst_gets_starting_virtual_balance(self):
        self.analyst.capper_balance.refresh_from_db()

        self.assertEqual(self.analyst.capper_balance.balance, Decimal("10000.00"))
        self.assertTrue(
            BalanceTransaction.objects.filter(
                user=self.analyst,
                kind=BalanceTransaction.Kind.INITIAL_BONUS,
                amount=Decimal("10000.00"),
            ).exists()
        )

    def test_publishing_coupon_charges_stake(self):
        self.client.force_login(self.analyst)

        response = self.client.post(
            reverse("game:create_coupon"),
            data=json.dumps(self._payload("500")),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["balance"], "9500.00")
        self.assertEqual(response.json()["balance_display"], "9 500")
        self.analyst.capper_balance.refresh_from_db()
        self.assertEqual(self.analyst.capper_balance.balance, Decimal("9500.00"))
        self.assertTrue(
            BalanceTransaction.objects.filter(
                user=self.analyst,
                kind=BalanceTransaction.Kind.PREDICTION_STAKE,
                amount=Decimal("-500.00"),
            ).exists()
        )

    def test_coupon_is_not_created_when_balance_is_too_low(self):
        self.analyst.capper_balance.balance = Decimal("50.00")
        self.analyst.capper_balance.save(update_fields=["balance", "updated_at"])
        self.client.force_login(self.analyst)

        response = self.client.post(
            reverse("game:create_coupon"),
            data=json.dumps(self._payload("500")),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 402)
        self.assertIn("Недостаточно средств", response.json()["error"])
        self.assertFalse(PredictionCoupon.objects.filter(author=self.analyst).exists())
        self.analyst.capper_balance.refresh_from_db()
        self.assertEqual(self.analyst.capper_balance.balance, Decimal("50.00"))

    def test_settled_winning_coupon_credits_payout_once(self):
        coupon = PredictionCoupon.objects.create(
            author=self.analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            total_stake=Decimal("100.00"),
            possible_payout=Decimal("250.00"),
            confidence=80,
            published_at=timezone.now(),
        )
        Prediction.objects.create(
            coupon=coupon,
            match=self.match,
            market="winner",
            selection="Хозяева",
            coefficient=Decimal("2.50"),
            stake=Decimal("100.00"),
            state_status=Prediction.StateStatus.WIN,
        )
        charge_prediction_stake(self.analyst, coupon, coupon.total_stake)

        settle_coupon(coupon.id)
        settle_coupon(coupon.id)

        self.analyst.capper_balance.refresh_from_db()
        self.assertEqual(self.analyst.capper_balance.balance, Decimal("10150.00"))
        self.assertEqual(
            BalanceTransaction.objects.filter(
                user=self.analyst,
                kind=BalanceTransaction.Kind.PREDICTION_PAYOUT,
                related_id=coupon.id,
            ).count(),
            1,
        )

    def test_top_up_view_adds_virtual_money_and_redirects_back(self):
        self.client.force_login(self.analyst)

        response = self.client.post(
            reverse("wallets:top_up"),
            data={"next": reverse("cabinet:profile")},
        )

        self.assertEqual(response.status_code, 302)
        self.analyst.capper_balance.refresh_from_db()
        self.assertEqual(self.analyst.capper_balance.balance, Decimal("20000.00"))
        self.assertTrue(
            BalanceTransaction.objects.filter(
                user=self.analyst,
                kind=BalanceTransaction.Kind.VIRTUAL_DEPOSIT,
                amount=Decimal("10000.00"),
            ).exists()
        )


@override_settings(STORAGES=TEST_STORAGES)
class CapperBalanceHeaderTests(TestCase):
    def test_analyst_header_shows_balance_and_top_up_button(self):
        analyst = User.objects.create_user(
            username="header-balance-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.client.force_login(analyst)

        response = self.client.get(reverse("front:index"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="nav-wallet"')
        self.assertContains(response, 'class="nav-wallet-topup"')
        self.assertContains(response, "10 000 ₽")
        self.assertContains(response, reverse("wallets:top_up"))
        self.assertContains(response, "Пополнить")

    def test_top_up_link_opens_wallet_methods_page(self):
        analyst = User.objects.create_user(
            username="wallet-page-capper",
            password="safe-test-password",
            role=User.Role.ANALYST,
        )
        self.client.force_login(analyst)

        response = self.client.get(reverse("wallets:top_up"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Способы пополнения")
        self.assertContains(response, "Виртуальное пополнение")
        self.assertContains(response, "10 000 ₽")
