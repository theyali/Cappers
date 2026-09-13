import importlib
from decimal import Decimal

from django.test import TestCase

from cabinet.models import User
from game.models import PredictionCoupon
from wallets.models import CapperRealBalance, CoinTransaction
from wallets.services import charge_prediction_stake, settle_prediction_coupon


cutover_migration = importlib.import_module(
    "wallets.migrations.0010_fix_legacy_rub_coin_cutover"
)


class LegacyCoinCutoverMathTests(TestCase):
    def test_historical_rate_is_fixed_at_five_rubles(self):
        self.assertEqual(
            cutover_migration.MIGRATION_COIN_PRICE_RUB,
            Decimal("5.00"),
        )
        self.assertEqual(
            cutover_migration._rub_balance_to_coins(Decimal("300.00")),
            60,
        )
        self.assertEqual(
            cutover_migration._rub_credit_to_coins(Decimal("600.00")),
            120,
        )

    def test_legacy_debit_rounds_up(self):
        self.assertEqual(
            cutover_migration._rub_debit_to_coins(Decimal("301.00")),
            61,
        )
        self.assertEqual(
            cutover_migration._legacy_transaction_amount_to_coins(
                Decimal("-301.00"),
                "prediction_stake",
            ),
            -61,
        )

    def test_legacy_refund_and_payout_are_positive_coins(self):
        self.assertEqual(
            cutover_migration._legacy_transaction_amount_to_coins(
                Decimal("301.00"),
                "prediction_refund",
            ),
            61,
        )
        self.assertEqual(
            cutover_migration._legacy_transaction_amount_to_coins(
                Decimal("600.00"),
                "prediction_payout",
            ),
            120,
        )

    def test_payout_uses_converted_stake_and_coefficient(self):
        self.assertEqual(
            cutover_migration._round_coin_payout(
                60,
                Decimal("2.00"),
            ),
            120,
        )

    def test_wallet_repair_preserves_post_cutover_coin_delta(self):
        # Legacy wallet was wrongly migrated as 300 coins instead of 60.
        # A later +200 coin operation must remain +200 after repair.
        self.assertEqual(
            cutover_migration._corrected_wallet_balance(
                current_balance=500,
                old_legacy_balance=300,
            ),
            260,
        )


class CoinStakePayoutRuntimeTests(TestCase):
    def test_coin_stake_and_payout_preserve_old_ruble_economic_ratio(self):
        analyst = User.objects.create_user(
            username="coin-economy-step2",
            password="test-password",
            role=User.Role.ANALYST,
        )
        real_balance, _ = CapperRealBalance.objects.get_or_create(
            user=analyst,
            defaults={"balance": Decimal("700.00")},
        )
        real_balance.balance = Decimal("700.00")
        real_balance.save(update_fields=["balance", "updated_at"])

        # Historical equivalent: 300 ₽ / 5 ₽ = 60 coins.
        # At coefficient 2.00 payout must be 120 coins (= old 600 ₽).
        coupon = PredictionCoupon.objects.create(
            author=analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=PredictionCoupon.StateStatus.WIN,
            total_stake=Decimal("60"),
            possible_payout=Decimal("120"),
            confidence=80,
        )

        charge_prediction_stake(analyst, coupon, coupon.total_stake)
        settle_prediction_coupon(coupon)

        analyst.coin_wallet.refresh_from_db()
        real_balance.refresh_from_db()

        self.assertEqual(analyst.coin_wallet.balance, 1060)
        self.assertEqual(real_balance.balance, Decimal("700.00"))
        self.assertTrue(
            CoinTransaction.objects.filter(
                user=analyst,
                kind=CoinTransaction.Kind.PREDICTION_STAKE,
                amount=-60,
                related_id=coupon.pk,
            ).exists()
        )
        self.assertTrue(
            CoinTransaction.objects.filter(
                user=analyst,
                kind=CoinTransaction.Kind.PREDICTION_PAYOUT,
                amount=120,
                related_id=coupon.pk,
            ).exists()
        )
