from datetime import datetime, timezone
from decimal import Decimal

from django.db import connection

from cabinet.models import User
from wallets import models as wallet_models
from wallets.models import CapperRealBalance, CoinTransaction, CoinWallet, RealBalanceTransaction


assert not hasattr(wallet_models, "CapperBalance")
assert not hasattr(wallet_models, "BalanceTransaction")
assert "virtual_top_up" not in RealBalanceTransaction.Kind.values

user = User.objects.get(username="legacy-migration-user")
wallet = CoinWallet.objects.get(user=user)
assert wallet.balance == 990, wallet.balance

initial = CoinTransaction.objects.get(
    user=user,
    kind="initial_bonus",
    note="legacy initial",
)
assert initial.amount == 1000
assert initial.balance_after == 1000

stake = CoinTransaction.objects.get(
    user=user,
    kind="prediction_stake",
    related_model="game.predictioncoupon",
    related_id=4242,
)
assert stake.amount == -11, stake.amount
assert stake.balance_after == 990, stake.balance_after
assert stake.note == "legacy stake"
assert stake.created_at == datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

marker = CoinTransaction.objects.get(user=user, kind="initial_grant")
assert marker.amount == 0
assert marker.balance_after == 990

real_wallet = CapperRealBalance.objects.get(user=user)
assert real_wallet.balance == Decimal("77.77")
real_tx = RealBalanceTransaction.objects.get(
    user=user,
    note="real balance must survive",
)
assert real_tx.balance_after == Decimal("77.77")

legacy_tables = {"wallets_capperbalance", "wallets_balancetransaction"}
assert not legacy_tables.intersection(connection.introspection.table_names())

new_user = User.objects.create_user(
    username="post-migration-user",
    password="safe-test-password",
    role=User.Role.READER,
)
new_user.coin_wallet.refresh_from_db()
assert new_user.coin_wallet.balance == 1000
assert CoinTransaction.objects.filter(
    user=new_user,
    kind=CoinTransaction.Kind.INITIAL_GRANT,
    amount=1000,
    balance_after=1000,
).count() == 1

print("CoinWallet count:", CoinWallet.objects.count())
print("CoinTransaction count:", CoinTransaction.objects.count())
print("legacy -> coin migration verified; real balance preserved")
