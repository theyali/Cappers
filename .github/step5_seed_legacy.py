from datetime import datetime, timezone
from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor


executor = MigrationExecutor(connection)
state = executor.loader.project_state([("wallets", "0007_coin_wallets")])
apps = state.apps

User = apps.get_model("cabinet", "User")
CapperBalance = apps.get_model("wallets", "CapperBalance")
BalanceTransaction = apps.get_model("wallets", "BalanceTransaction")
CapperRealBalance = apps.get_model("wallets", "CapperRealBalance")
RealBalanceTransaction = apps.get_model("wallets", "RealBalanceTransaction")

user = User.objects.create(
    username="legacy-migration-user",
    password="!",
    role="reader",
)
stamp = datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

legacy_wallet = CapperBalance.objects.create(
    user_id=user.pk,
    balance=Decimal("989.50"),
)
CapperBalance.objects.filter(pk=legacy_wallet.pk).update(
    created_at=stamp,
    updated_at=stamp,
)

initial_tx = BalanceTransaction.objects.create(
    user_id=user.pk,
    kind="initial_bonus",
    amount=Decimal("1000.00"),
    balance_after=Decimal("1000.00"),
    note="legacy initial",
)
BalanceTransaction.objects.filter(pk=initial_tx.pk).update(created_at=stamp)

stake_tx = BalanceTransaction.objects.create(
    user_id=user.pk,
    kind="prediction_stake",
    amount=Decimal("-10.50"),
    balance_after=Decimal("989.50"),
    related_model="game.predictioncoupon",
    related_id=4242,
    note="legacy stake",
)
BalanceTransaction.objects.filter(pk=stake_tx.pk).update(created_at=stamp)

real_wallet = CapperRealBalance.objects.create(
    user_id=user.pk,
    balance=Decimal("77.77"),
    pending_withdrawal=Decimal("0.00"),
)
real_tx = RealBalanceTransaction.objects.create(
    user_id=user.pk,
    kind="adjustment",
    status="completed",
    amount=Decimal("10.00"),
    balance_after=Decimal("77.77"),
    note="real balance must survive",
)

print("legacy fixture seeded", user.pk, real_wallet.pk, real_tx.pk)
