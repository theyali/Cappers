from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from cabinet.models import User
from wallets.models import CoinPackage
from wallets.package_pricing import (
    effective_coin_price_rub,
    format_effective_coin_price_rub,
)


class PackagePricingTests(SimpleTestCase):
    def test_effective_price_uses_package_total_coins_not_base_rate(self):
        self.assertEqual(
            effective_coin_price_rub(Decimal("500.00"), 1000),
            Decimal("0.5000"),
        )
        self.assertEqual(
            effective_coin_price_rub(Decimal("1000.00"), 10000),
            Decimal("0.1000"),
        )

    def test_bonus_coins_lower_effective_package_price(self):
        without_bonus = effective_coin_price_rub(Decimal("500.00"), 1000)
        with_bonus = effective_coin_price_rub(Decimal("500.00"), 2000)

        self.assertEqual(without_bonus, Decimal("0.5000"))
        self.assertEqual(with_bonus, Decimal("0.2500"))
        self.assertLess(with_bonus, without_bonus)
        self.assertEqual(
            format_effective_coin_price_rub(Decimal("500.00"), 2000),
            "0.25",
        )


class CoinPackageUxTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="package-reader",
            password="safe-test-password",
            role=User.Role.READER,
        )
        self.package = CoinPackage.objects.create(
            title="Стартовый пакет",
            coins=1000,
            bonus_coins=0,
            price_rub=Decimal("500.00"),
        )
        self.client.force_login(self.user)

    def test_top_up_separates_internal_coins_from_purchase_rubles(self):
        response = self.client.get(reverse("wallets:top_up"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Коины — внутренняя валюта сайта")
        self.assertContains(response, "coins за <strong>500 ₽</strong>", html=False)
        self.assertContains(response, "примерно 1 coin = 0.5 ₽")
        self.assertContains(response, "front/img/coin.svg")
