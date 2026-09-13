from decimal import Decimal, ROUND_HALF_UP

from django.db import migrations


COIN_UNIT = Decimal("1")
INITIAL_GRANT_KIND = "initial_grant"


def _to_coins(value):
    """Conversion rule: 1 legacy virtual-balance unit = 1 coin."""
    return int(Decimal(value).quantize(COIN_UNIT, rounding=ROUND_HALF_UP))


def migrate_virtual_balance_to_coins(apps, schema_editor):
    CapperBalance = apps.get_model("wallets", "CapperBalance")
    BalanceTransaction = apps.get_model("wallets", "BalanceTransaction")
    CoinWallet = apps.get_model("wallets", "CoinWallet")
    CoinTransaction = apps.get_model("wallets", "CoinTransaction")

    for legacy_wallet in CapperBalance.objects.order_by("user_id").iterator():
        coin_balance = _to_coins(legacy_wallet.balance)
        if coin_balance < 0:
            raise RuntimeError(
                f"Cannot migrate negative virtual balance for user {legacy_wallet.user_id}: "
                f"{legacy_wallet.balance}"
            )

        coin_wallet, _ = CoinWallet.objects.update_or_create(
            user_id=legacy_wallet.user_id,
            defaults={"balance": coin_balance},
        )
        CoinWallet.objects.filter(pk=coin_wallet.pk).update(
            created_at=legacy_wallet.created_at,
            updated_at=legacy_wallet.updated_at,
        )

        # A zero-value grant marker prevents the current runtime from adding a fresh
        # initial grant on top of an already migrated legacy balance.
        marker, marker_created = CoinTransaction.objects.get_or_create(
            user_id=legacy_wallet.user_id,
            kind=INITIAL_GRANT_KIND,
            defaults={
                "amount": 0,
                "balance_after": coin_balance,
                "related_model": "",
                "related_id": None,
                "note": "Миграция: стартовые коины уже учтены в перенесенном балансе",
            },
        )
        if marker_created:
            CoinTransaction.objects.filter(pk=marker.pk).update(
                created_at=legacy_wallet.created_at,
            )

    for legacy_tx in BalanceTransaction.objects.order_by("id").iterator():
        amount = _to_coins(legacy_tx.amount)
        balance_after = _to_coins(legacy_tx.balance_after)
        if balance_after < 0:
            raise RuntimeError(
                f"Cannot migrate negative balance_after in legacy transaction {legacy_tx.pk}: "
                f"{legacy_tx.balance_after}"
            )

        defaults = {
            "amount": amount,
            "balance_after": balance_after,
            "note": legacy_tx.note,
        }
        if legacy_tx.related_id is not None:
            coin_tx, _ = CoinTransaction.objects.update_or_create(
                user_id=legacy_tx.user_id,
                kind=legacy_tx.kind,
                related_model=legacy_tx.related_model,
                related_id=legacy_tx.related_id,
                defaults=defaults,
            )
        else:
            coin_tx = CoinTransaction.objects.create(
                user_id=legacy_tx.user_id,
                kind=legacy_tx.kind,
                amount=amount,
                balance_after=balance_after,
                related_model=legacy_tx.related_model,
                related_id=None,
                note=legacy_tx.note,
            )

        CoinTransaction.objects.filter(pk=coin_tx.pk).update(
            created_at=legacy_tx.created_at,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("wallets", "0007_coin_wallets"),
    ]

    operations = [
        migrations.RunPython(
            migrate_virtual_balance_to_coins,
            migrations.RunPython.noop,
        ),
    ]
