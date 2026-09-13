from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from wallets.coin_economy import coins_to_rub, get_coin_price_rub, rub_to_coins
from wallets.models import CoinSettings


class CoinEconomyTests(TestCase):
    def setUp(self):
        CoinSettings.objects.update_or_create(
            pk=1,
            defaults={
                "coin_price_rub": Decimal("5.00"),
                "initial_grant": 1000,
                "is_enabled": True,
            },
        )

    def test_configured_coin_price_is_single_source_of_truth(self):
        self.assertEqual(get_coin_price_rub(), Decimal("5.00"))
        self.assertEqual(rub_to_coins(Decimal("300.00")), 60)
        self.assertEqual(rub_to_coins(Decimal("600.00")), 120)
        self.assertEqual(coins_to_rub(60), Decimal("300.00"))
        self.assertEqual(coins_to_rub(120), Decimal("600.00"))

    def test_rub_to_coins_rounds_up_for_debit_amounts(self):
        self.assertEqual(rub_to_coins(Decimal("301.00")), 61)
        self.assertEqual(rub_to_coins(Decimal("0.01")), 1)
        self.assertEqual(rub_to_coins(Decimal("0.00")), 0)

    def test_coins_to_rub_rounds_display_equivalent_down(self):
        self.assertEqual(
            coins_to_rub(3, coin_price_rub=Decimal("0.333")),
            Decimal("0.99"),
        )

    def test_coin_price_must_be_positive(self):
        settings = CoinSettings.load()

        settings.coin_price_rub = Decimal("0.00")
        with self.assertRaises(ValidationError):
            settings.full_clean()

        settings.coin_price_rub = Decimal("-1.00")
        with self.assertRaises(ValidationError):
            settings.full_clean()

    def test_conversion_rejects_non_positive_explicit_rate(self):
        for price in (Decimal("0"), Decimal("-5")):
            with self.subTest(price=price):
                with self.assertRaises(ValidationError):
                    rub_to_coins(Decimal("300.00"), coin_price_rub=price)

    def test_coin_amount_for_ruble_equivalent_must_be_integer(self):
        with self.assertRaises(ValidationError):
            coins_to_rub(Decimal("1.5"))
