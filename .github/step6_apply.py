from pathlib import Path


def replace_once(path, old, new):
    file_path = Path(path)
    text = file_path.read_text()
    if old not in text:
        raise SystemExit(f"Expected text not found in {path}: {old!r}")
    file_path.write_text(text.replace(old, new, 1))


def replace_all(path, old, new):
    file_path = Path(path)
    text = file_path.read_text()
    if old not in text:
        raise SystemExit(f"Expected text not found in {path}: {old!r}")
    file_path.write_text(text.replace(old, new))


# Separate coin insufficiency from real-money insufficiency while preserving
# InsufficientCoins as the specific coin exception used by current callers.
replace_once(
    "wallets/services.py",
    '''class InsufficientBalance(Exception):\n    """Insufficient real-money balance."""\n\n\nclass InsufficientCoins(ValidationError):\n    """Insufficient application coins."""\n''',
    '''class InsufficientBalance(ValidationError):\n    """Insufficient application coin balance."""\n\n\nclass InsufficientCoins(InsufficientBalance):\n    """Specific insufficient-coins error for coin operations."""\n\n\nclass InsufficientRealBalance(Exception):\n    """Insufficient real-money balance."""\n''',
)
replace_once(
    "wallets/services.py",
    '''            raise InsufficientBalance(\n                f"Недостаточно средств на реальном балансе. Доступно {balance.balance} ₽, нужно {amount} ₽."\n            )\n''',
    '''            raise InsufficientRealBalance(\n                f"Недостаточно средств на реальном балансе. Доступно {balance.balance} ₽, нужно {amount} ₽."\n            )\n''',
)
replace_once(
    "wallets/views.py",
    '''    InsufficientBalance,\n    activate_copybetting,\n''',
    '''    InsufficientRealBalance,\n    activate_copybetting,\n''',
)
replace_once(
    "wallets/views.py",
    '''    except (ValidationError, InsufficientBalance) as exc:\n''',
    '''    except (ValidationError, InsufficientRealBalance) as exc:\n''',
)

# Strengthen wallet integration tests for step 6.
replace_once(
    "wallets/tests.py",
    '''from django.urls import reverse\n''',
    '''from django.urls import reverse\n\nfrom wallets import services as wallet_services\n''',
)
replace_once(
    "wallets/tests.py",
    '''from wallets.services import (\n    activate_copybetting,\n''',
    '''from wallets.services import (\n    InsufficientBalance,\n    activate_copybetting,\n''',
)
replace_once(
    "wallets/tests.py",
    '''    pause_copybetting,\n    request_real_withdrawal,\n''',
    '''    pause_copybetting,\n    purchase_coin_package,\n    request_real_withdrawal,\n''',
)
replace_once(
    "wallets/tests.py",
    '''    def test_top_up_post_does_not_mint_coins_without_payment(self):\n''',
    '''    def test_purchase_coin_package_credits_coins_and_bonus(self):\n        package = CoinPackage.objects.create(\n            title="Пакет с бонусом",\n            coins=1000,\n            bonus_coins=150,\n            price_rub=Decimal("500.00"),\n        )\n\n        wallet = purchase_coin_package(self.analyst, package)\n\n        self.assertEqual(wallet.balance, 2150)\n        self.assertTrue(\n            CoinTransaction.objects.filter(\n                user=self.analyst,\n                kind=CoinTransaction.Kind.PACKAGE_PURCHASE,\n                amount=1150,\n                balance_after=2150,\n            ).exists()\n        )\n\n    def test_prediction_refund_returns_stake_in_coins(self):\n        coupon = PredictionCoupon.objects.create(\n            author=self.analyst,\n            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,\n            total_stake=Decimal("100.00"),\n            possible_payout=Decimal("100.00"),\n            confidence=80,\n            published_at=timezone.now(),\n        )\n        Prediction.objects.create(\n            coupon=coupon,\n            match=self.match,\n            market="winner",\n            selection="Хозяева",\n            coefficient=Decimal("1.00"),\n            stake=Decimal("100.00"),\n            state_status=Prediction.StateStatus.REFUND,\n        )\n        charge_prediction_stake(self.analyst, coupon, coupon.total_stake)\n\n        settle_coupon(coupon.id)\n\n        self.analyst.coin_wallet.refresh_from_db()\n        self.assertEqual(self.analyst.coin_wallet.balance, 1000)\n        self.assertTrue(\n            CoinTransaction.objects.filter(\n                user=self.analyst,\n                kind=CoinTransaction.Kind.PREDICTION_REFUND,\n                amount=100,\n                balance_after=1000,\n                related_id=coupon.id,\n            ).exists()\n        )\n\n    def test_insufficient_coin_balance_raises_insufficient_balance_with_coin_text(self):\n        coupon = PredictionCoupon.objects.create(\n            author=self.analyst,\n            total_stake=Decimal("1001.00"),\n            possible_payout=Decimal("1001.00"),\n            confidence=70,\n        )\n\n        with self.assertRaisesMessage(InsufficientBalance, "Недостаточно коинов"):\n            charge_prediction_stake(self.analyst, coupon, Decimal("1001.00"))\n\n        self.analyst.coin_wallet.refresh_from_db()\n        self.assertEqual(self.analyst.coin_wallet.balance, 1000)\n\n    def test_old_real_to_virtual_transfer_is_unavailable_and_cannot_mint_coins(self):\n        self.assertFalse(hasattr(wallet_services, "transfer_real_to_virtual"))\n        self.analyst.real_balance.balance = Decimal("500.00")\n        self.analyst.real_balance.save(update_fields=["balance", "updated_at"])\n        self.client.force_login(self.analyst)\n\n        response = self.client.post(\n            reverse("wallets:real_action"),\n            data={"action": "transfer_real_to_virtual", "amount": "100.00"},\n        )\n\n        self.assertEqual(response.status_code, 302)\n        self.analyst.real_balance.refresh_from_db()\n        self.analyst.coin_wallet.refresh_from_db()\n        self.assertEqual(self.analyst.real_balance.balance, Decimal("500.00"))\n        self.assertEqual(self.analyst.coin_wallet.balance, 1000)\n\n    def test_top_up_post_does_not_mint_coins_without_payment(self):\n''',
)
replace_once(
    "wallets/tests.py",
    '''        reader.coin_wallet.refresh_from_db()\n        self.assertEqual(reader.coin_wallet.balance, 1100)\n        subscription = CopyBettingSubscription.objects.get(user=reader, analyst=self.analyst)\n''',
    '''        reader.coin_wallet.refresh_from_db()\n        self.assertEqual(reader.coin_wallet.balance, 1100)\n        self.assertTrue(\n            CoinTransaction.objects.filter(\n                user=reader,\n                kind=CoinTransaction.Kind.COPYBET_PAYOUT,\n                amount=200,\n                balance_after=1100,\n            ).exists()\n        )\n        subscription = CopyBettingSubscription.objects.get(user=reader, analyst=self.analyst)\n''',
)

# Wallet UI tests should assert the SVG-backed coin presentation, not stale text.
replace_once(
    "wallets/tests.py",
    '''        self.assertContains(response, "1 000 коинов")\n        self.assertContains(response, reverse("wallets:top_up"))\n''',
    '''        self.assertContains(response, 'class="coin-icon"')\n        self.assertContains(response, 'data-wallet-balance')\n        self.assertContains(response, "1 000")\n        self.assertContains(response, reverse("wallets:top_up"))\n''',
)
replace_once(
    "wallets/tests.py",
    '''        self.assertContains(response, "1 000 коинов")\n        self.assertContains(response, "500.00 ₽")\n''',
    '''        self.assertContains(response, 'class="coin-icon"')\n        self.assertContains(response, "1 000")\n        self.assertContains(response, "500,00 ₽")\n''',
)

# Roulette reward must be a coin-ledger operation only.
replace_once(
    "cabinet/tests/test_roulette_api.py",
    '''from django.test import Client, TestCase, TransactionTestCase\n''',
    '''from django.test import Client, TestCase, TransactionTestCase, override_settings\n''',
)
replace_once(
    "cabinet/tests/test_roulette_api.py",
    '''from wallets.services import ensure_coin_wallet\n\n\nclass RouletteApiTests(TestCase):\n''',
    '''from wallets.services import ensure_coin_wallet\n\n\nTEST_STORAGES = {\n    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},\n    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},\n}\n\n\n@override_settings(STORAGES=TEST_STORAGES)\nclass RouletteApiTests(TestCase):\n''',
)
replace_once(
    "cabinet/tests/test_roulette_api.py",
    '''        self.assertEqual(\n            CoinTransaction.objects.filter(\n                user=self.user,\n                kind=CoinTransaction.Kind.ROULETTE_REWARD,\n                related_id=first_payload["spin_id"],\n            ).count(),\n            1,\n        )\n''',
    '''        transaction = CoinTransaction.objects.get(\n            user=self.user,\n            kind=CoinTransaction.Kind.ROULETTE_REWARD,\n            related_id=first_payload["spin_id"],\n        )\n        self.assertEqual(transaction.amount, 250)\n        self.assertEqual(transaction.balance_after, starting_balance + 250)\n        self.assertNotIn("₽", json.dumps(first_payload, ensure_ascii=False))\n''',
)

# Tournament coupon API and prize settlement: stake/profit are coins, prize is real money.
replace_once(
    "tournaments/tests.py",
    '''from tournaments.services.rules import TournamentRuleError, validate_tournament_coupon\n''',
    '''from tournaments.services.rules import TournamentRuleError, validate_tournament_coupon\nfrom wallets.models import CoinTransaction, RealBalanceTransaction\n''',
)
replace_once(
    "tournaments/tests.py",
    '''        self.assertEqual(results[0].prize_amount, Decimal("1000.00"))\n''',
    '''        self.assertEqual(results[0].prize_amount, Decimal("1000.00"))\n        self.analyst.real_balance.refresh_from_db()\n        self.analyst.coin_wallet.refresh_from_db()\n        self.assertEqual(self.analyst.real_balance.balance, Decimal("1000.00"))\n        self.assertEqual(self.analyst.coin_wallet.balance, 1000)\n        self.assertTrue(\n            RealBalanceTransaction.objects.filter(\n                user=self.analyst,\n                kind=RealBalanceTransaction.Kind.TOURNAMENT_PRIZE,\n                amount=Decimal("1000.00"),\n            ).exists()\n        )\n        self.assertFalse(\n            CoinTransaction.objects.filter(\n                user=self.analyst,\n                kind=CoinTransaction.Kind.ADJUSTMENT,\n            ).exists()\n        )\n''',
)
replace_once(
    "tournaments/tests.py",
    '''        self.assertEqual(payload["message"], "Прогноз турнира опубликован.")\n        self.assertEqual(payload["balance"], "9800.00")\n        self.assertEqual(PredictionCoupon.objects.count(), 1)\n''',
    '''        self.assertEqual(payload["message"], "Прогноз турнира опубликован.")\n        self.assertEqual(payload["coin_balance"], 800)\n        self.assertEqual(payload["coin_balance_display"], "800")\n        self.assertNotIn("balance", payload)\n        self.assertEqual(PredictionCoupon.objects.count(), 1)\n        self.analyst.coin_wallet.refresh_from_db()\n        self.assertEqual(self.analyst.coin_wallet.balance, 800)\n''',
)

# Coin UI: no ruble symbol for prediction stakes/payouts, copybetting or simulated profit.
replace_once(
    "templates/front/_prediction_card.html",
    '''            <strong>{{ prediction.coupon.total_stake|money }} ₽</strong>\n''',
    '''            <strong><span class="coin-amount">{% include "front/includes/_coin_icon.html" %}<span>{{ prediction.coupon.total_stake|floatformat:"0" }}</span></span></strong>\n''',
)
replace_once(
    "templates/front/_prediction_card.html",
    '''            <strong>{{ prediction.coupon.possible_payout|money }} ₽</strong>\n''',
    '''            <strong><span class="coin-amount">{% include "front/includes/_coin_icon.html" %}<span>{{ prediction.coupon.possible_payout|floatformat:"0" }}</span></span></strong>\n''',
)
replace_once(
    "templates/cabinet/_coupon_slip.html",
    '''            <strong>{{ coupon.total_stake|money }} ₽</strong>\n''',
    '''            <strong><span class="coin-amount">{% include "front/includes/_coin_icon.html" %}<span>{{ coupon.total_stake|floatformat:"0" }}</span></span></strong>\n''',
)
replace_once(
    "templates/cabinet/_coupon_slip.html",
    '''            <strong>{{ coupon.possible_payout|money }} ₽</strong>\n''',
    '''            <strong><span class="coin-amount">{% include "front/includes/_coin_icon.html" %}<span>{{ coupon.possible_payout|floatformat:"0" }}</span></span></strong>\n''',
)

bank_replacements = {
    '{{ bank_total_stake|money }} ₽': '<span class="coin-amount">{% include "front/includes/_coin_icon.html" %}<span>{{ bank_total_stake|floatformat:"0" }}</span></span>',
    '{{ bank_lost_amount|money }} ₽': '<span class="coin-amount">{% include "front/includes/_coin_icon.html" %}<span>{{ bank_lost_amount|floatformat:"0" }}</span></span>',
    '{{ bank_earned_amount|money }} ₽': '<span class="coin-amount">{% include "front/includes/_coin_icon.html" %}<span>{{ bank_earned_amount|floatformat:"0" }}</span></span>',
    '{{ bank_net_result|money }} ₽': '<span class="coin-amount">{% include "front/includes/_coin_icon.html" %}<span>{{ bank_net_result|floatformat:"0" }}</span></span>',
    '{{ bank_average_stake|money }} ₽': '<span class="coin-amount">{% include "front/includes/_coin_icon.html" %}<span>{{ bank_average_stake|floatformat:"0" }}</span></span>',
    '{{ bank_pending_stake|money }} ₽': '<span class="coin-amount">{% include "front/includes/_coin_icon.html" %}<span>{{ bank_pending_stake|floatformat:"0" }}</span></span>',
}
for old, new in bank_replacements.items():
    replace_once("templates/cabinet/_expert_public_bank.html", old, new)

replace_once(
    "templates/cabinet/_expert_monthly_stats.html",
    '''                    <td title="Фактическая прибыль: {{ row.total_profit|money }} ₽ · оборот: {{ row.total_stake|money }} ₽">\n''',
    '''                    <td title="Фактическая прибыль: {{ row.total_profit|floatformat:'0' }} коинов · оборот: {{ row.total_stake|floatformat:'0' }} коинов">\n''',
)
replace_once(
    "templates/cabinet/_expert_tournament_row.html",
    '''        <strong class="{% if row.profit > 0 %}is-positive{% elif row.profit < 0 %}is-negative{% endif %}">{{ row.profit|money }} ₽</strong>\n''',
    '''        <strong class="{% if row.profit > 0 %}is-positive{% elif row.profit < 0 %}is-negative{% endif %}"><span class="coin-amount">{% include "front/includes/_coin_icon.html" %}<span>{{ row.profit|floatformat:"0" }}</span></span></strong>\n''',
)
replace_once(
    "templates/cabinet/_profile_dashboard.html",
    '''                <strong>{{ copybetting_audience_profit_display }} ₽</strong>\n''',
    '''                <strong><span class="coin-amount">{% include "front/includes/_coin_icon.html" %}<span>{{ copybetting_audience_profit_display }}</span></span></strong>\n''',
)
replace_once(
    "templates/tournaments/detail.html",
    '''                                        <strong>{{ row.profit|money }} ₽</strong>\n''',
    '''                                        <strong><span class="coin-amount">{% include "front/includes/_coin_icon.html" %}<span>{{ row.profit|floatformat:"0" }}</span></span></strong>\n''',
)
