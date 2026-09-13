from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from cabinet.models import User

from .models import CoinPackage, CoinSettings, CoinTransaction
from .services import (
    InsufficientCoins,
    adjust_coin_balance,
    charge_coins,
    credit_coins,
    ensure_coin_wallet,
    purchase_coin_package,
)


class CoinWalletTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="coin-user",
            password="safe-test-password",
            role=User.Role.READER,
        )

    def test_ensure_coin_wallet_applies_initial_grant_once(self):
        wallet = ensure_coin_wallet(self.user)

        self.assertEqual(wallet.balance, 1000)
        self.assertEqual(
            CoinTransaction.objects.filter(
                user=self.user,
                kind=CoinTransaction.Kind.INITIAL_GRANT,
                amount=1000,
                balance_after=1000,
            ).count(),
            1,
        )

        ensure_coin_wallet(self.user)
        ensure_coin_wallet(self.user)
        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, 1000)
        self.assertEqual(
            CoinTransaction.objects.filter(
                user=self.user,
                kind=CoinTransaction.Kind.INITIAL_GRANT,
            ).count(),
            1,
        )

    def test_coin_settings_are_singleton(self):
        settings_row = CoinSettings.load()
        settings_row.coin_price_rub = Decimal("3.50")
        settings_row.save()

        another = CoinSettings()
        another.coin_price_rub = Decimal("7.00")
        another.save()

        self.assertEqual(CoinSettings.objects.count(), 1)
        self.assertEqual(CoinSettings.load().pk, 1)
        self.assertEqual(CoinSettings.load().coin_price_rub, Decimal("7.00"))

    def test_admin_adjustment_uses_integer_ledger(self):
        adjust_coin_balance(self.user, 250, note="Тестовое начисление")
        adjust_coin_balance(self.user, -100, note="Тестовое списание")

        wallet = self.user.coin_wallet
        wallet.refresh_from_db()
        self.assertEqual(wallet.balance, 1150)
        self.assertEqual(
            list(
                CoinTransaction.objects.filter(
                    user=self.user,
                    kind=CoinTransaction.Kind.ADJUSTMENT,
                )
                .order_by("created_at", "id")
                .values_list("amount", "balance_after")
            ),
            [(250, 1250), (-100, 1150)],
        )

    def test_fractional_and_overdraft_adjustments_are_rejected(self):
        with self.assertRaises(ValidationError):
            adjust_coin_balance(self.user, "1.5")
        with self.assertRaises(ValidationError):
            adjust_coin_balance(self.user, -2000)

        self.user.coin_wallet.refresh_from_db()
        self.assertEqual(self.user.coin_wallet.balance, 1000)
        self.assertFalse(
            CoinTransaction.objects.filter(
                user=self.user,
                kind=CoinTransaction.Kind.ADJUSTMENT,
            ).exists()
        )

    def test_public_coin_api_accepts_only_integer_amounts(self):
        for invalid_amount in (Decimal("10"), Decimal("10.50"), "10", 10.5, True):
            with self.subTest(invalid_amount=invalid_amount):
                with self.assertRaises(ValidationError):
                    credit_coins(
                        self.user,
                        invalid_amount,
                        CoinTransaction.Kind.DAILY_TASK_REWARD,
                    )

        self.user.coin_wallet.refresh_from_db()
        self.assertEqual(self.user.coin_wallet.balance, 1000)

    def test_charge_coins_prevents_overdraft_and_writes_no_failed_ledger(self):
        with self.assertRaises(InsufficientCoins):
            charge_coins(
                self.user,
                1001,
                CoinTransaction.Kind.PREDICTION_STAKE,
            )

        self.user.coin_wallet.refresh_from_db()
        self.assertEqual(self.user.coin_wallet.balance, 1000)
        self.assertFalse(
            CoinTransaction.objects.filter(
                user=self.user,
                kind=CoinTransaction.Kind.PREDICTION_STAKE,
            ).exists()
        )

    def test_related_coin_credit_is_idempotent(self):
        credit_coins(
            self.user,
            75,
            CoinTransaction.Kind.DAILY_TASK_REWARD,
            related_obj=self.user,
            note="Ежедневное задание",
        )
        credit_coins(
            self.user,
            75,
            CoinTransaction.Kind.DAILY_TASK_REWARD,
            related_obj=self.user,
            note="Повтор запроса",
        )

        self.user.coin_wallet.refresh_from_db()
        self.assertEqual(self.user.coin_wallet.balance, 1075)
        self.assertEqual(
            CoinTransaction.objects.filter(
                user=self.user,
                kind=CoinTransaction.Kind.DAILY_TASK_REWARD,
                related_id=self.user.pk,
            ).count(),
            1,
        )

    def test_related_coin_charge_is_idempotent(self):
        charge_coins(
            self.user,
            100,
            CoinTransaction.Kind.PREDICTION_STAKE,
            related_obj=self.user,
            note="Первая попытка списания",
        )
        charge_coins(
            self.user,
            100,
            CoinTransaction.Kind.PREDICTION_STAKE,
            related_obj=self.user,
            note="Повтор того же списания",
        )

        self.user.coin_wallet.refresh_from_db()
        self.assertEqual(self.user.coin_wallet.balance, 900)
        self.assertEqual(
            CoinTransaction.objects.filter(
                user=self.user,
                kind=CoinTransaction.Kind.PREDICTION_STAKE,
                related_id=self.user.pk,
            ).count(),
            1,
        )

    def test_coin_package_keeps_rubles_decimal_and_coins_integer(self):
        package = CoinPackage.objects.create(
            title="Стартовый пакет",
            coins=1000,
            bonus_coins=100,
            price_rub=Decimal("500.00"),
        )

        self.assertEqual(package.total_coins, 1100)
        self.assertIsInstance(package.coins, int)
        self.assertEqual(package.price_rub, Decimal("500.00"))

    def test_purchase_coin_package_credits_integer_coins(self):
        package = CoinPackage.objects.create(
            title="Большой пакет",
            coins=2000,
            bonus_coins=250,
            price_rub=Decimal("900.00"),
        )

        wallet = purchase_coin_package(self.user, package)

        self.assertEqual(wallet.balance, 3250)
        transaction = CoinTransaction.objects.get(
            user=self.user,
            kind=CoinTransaction.Kind.PACKAGE_PURCHASE,
        )
        self.assertEqual(transaction.amount, 2250)
        self.assertEqual(transaction.balance_after, 3250)
        self.assertIsInstance(transaction.amount, int)

    def test_purchase_coin_package_is_idempotent_for_same_payment(self):
        package = CoinPackage.objects.create(
            title="Пакет с платежом",
            coins=1000,
            bonus_coins=100,
            price_rub=Decimal("500.00"),
        )

        purchase_coin_package(self.user, package, payment=self.user)
        wallet = purchase_coin_package(self.user, package, payment=self.user)

        self.assertEqual(wallet.balance, 2100)
        self.assertEqual(
            CoinTransaction.objects.filter(
                user=self.user,
                kind=CoinTransaction.Kind.PACKAGE_PURCHASE,
                related_id=self.user.pk,
            ).count(),
            1,
        )
