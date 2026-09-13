from decimal import Decimal

import django.core.validators
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def seed_coin_wallets(apps, schema_editor):
    CoinSettings = apps.get_model("wallets", "CoinSettings")
    CoinTransaction = apps.get_model("wallets", "CoinTransaction")
    CoinWallet = apps.get_model("wallets", "CoinWallet")
    user_app_label, user_model_name = settings.AUTH_USER_MODEL.split(".")
    User = apps.get_model(user_app_label, user_model_name)

    coin_settings, _ = CoinSettings.objects.get_or_create(
        pk=1,
        defaults={
            "coin_price_rub": Decimal("5.00"),
            "initial_grant": 1000,
            "is_enabled": True,
        },
    )
    initial_grant = int(coin_settings.initial_grant) if coin_settings.is_enabled else 0

    for user_id in User.objects.values_list("pk", flat=True).iterator(chunk_size=1000):
        wallet, _ = CoinWallet.objects.get_or_create(
            user_id=user_id,
            defaults={"balance": initial_grant},
        )
        if initial_grant <= 0:
            continue
        CoinTransaction.objects.get_or_create(
            user_id=user_id,
            kind="initial_grant",
            defaults={
                "amount": initial_grant,
                "balance_after": wallet.balance,
                "note": "Стартовые коины",
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ("wallets", "0006_real_balance_referral_kinds"),
    ]

    operations = [
        migrations.CreateModel(
            name="CoinPackage",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("title", models.CharField(max_length=80, verbose_name="Название")),
                (
                    "coins",
                    models.PositiveIntegerField(
                        validators=[django.core.validators.MinValueValidator(1)],
                        verbose_name="Коины",
                    ),
                ),
                (
                    "price_rub",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=12,
                        validators=[django.core.validators.MinValueValidator(Decimal("0.01"))],
                        verbose_name="Цена, ₽",
                    ),
                ),
                ("bonus_coins", models.PositiveIntegerField(default=0, verbose_name="Бонусные коины")),
                ("is_active", models.BooleanField(db_index=True, default=True, verbose_name="Активен")),
                ("order", models.PositiveSmallIntegerField(db_index=True, default=0, verbose_name="Порядок")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создан")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлен")),
            ],
            options={
                "verbose_name": "Пакет коинов",
                "verbose_name_plural": "Пакеты коинов",
                "ordering": ["order", "id"],
            },
        ),
        migrations.CreateModel(
            name="CoinSettings",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "coin_price_rub",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("5.00"),
                        max_digits=10,
                        validators=[django.core.validators.MinValueValidator(Decimal("0.01"))],
                        verbose_name="Цена 1 коина, ₽",
                    ),
                ),
                ("initial_grant", models.PositiveIntegerField(default=1000, verbose_name="Стартовые коины")),
                ("is_enabled", models.BooleanField(default=True, verbose_name="Коины включены")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создано")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлено")),
            ],
            options={
                "verbose_name": "Настройки коинов",
                "verbose_name_plural": "Настройки коинов",
            },
        ),
        migrations.CreateModel(
            name="CoinWallet",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("balance", models.PositiveBigIntegerField(default=0, verbose_name="Коины")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создан")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлен")),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="coin_wallet",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Пользователь",
                    ),
                ),
            ],
            options={
                "verbose_name": "Кошелек коинов",
                "verbose_name_plural": "Кошельки коинов",
                "ordering": ["user_id"],
            },
        ),
        migrations.CreateModel(
            name="CoinTransaction",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("initial_grant", "Стартовые коины"),
                            ("package_purchase", "Покупка пакета"),
                            ("roulette_reward", "Приз рулетки"),
                            ("prediction_stake", "Списание за прогноз"),
                            ("prediction_payout", "Выплата по прогнозу"),
                            ("prediction_refund", "Возврат прогноза"),
                            ("copybet_stake", "Списание за копиставку"),
                            ("copybet_payout", "Выплата по копиставке"),
                            ("copybet_refund", "Возврат копиставки"),
                            ("daily_task_reward", "Ежедневное задание"),
                            ("adjustment", "Корректировка"),
                        ],
                        db_index=True,
                        max_length=32,
                        verbose_name="Тип",
                    ),
                ),
                ("amount", models.BigIntegerField(verbose_name="Изменение коинов")),
                ("balance_after", models.PositiveBigIntegerField(verbose_name="Коинов после операции")),
                ("related_model", models.CharField(blank=True, max_length=100, verbose_name="Связанная модель")),
                ("related_id", models.PositiveBigIntegerField(blank=True, null=True, verbose_name="Связанный объект")),
                ("note", models.CharField(blank=True, max_length=255, verbose_name="Комментарий")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создана")),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="coin_transactions",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Пользователь",
                    ),
                ),
            ],
            options={
                "verbose_name": "Транзакция коинов",
                "verbose_name_plural": "Транзакции коинов",
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.AddConstraint(
            model_name="coinwallet",
            constraint=models.CheckConstraint(
                condition=models.Q(("balance__gte", 0)),
                name="coin_wallet_balance_nonneg",
            ),
        ),
        migrations.AddConstraint(
            model_name="cointransaction",
            constraint=models.UniqueConstraint(
                condition=models.Q(("kind", "initial_grant")),
                fields=("user", "kind"),
                name="unique_coin_initial_grant",
            ),
        ),
        migrations.AddConstraint(
            model_name="cointransaction",
            constraint=models.UniqueConstraint(
                condition=models.Q(("related_id__isnull", False)),
                fields=("user", "kind", "related_model", "related_id"),
                name="unique_coin_transaction_subject",
            ),
        ),
        migrations.AddConstraint(
            model_name="cointransaction",
            constraint=models.CheckConstraint(
                condition=models.Q(("balance_after__gte", 0)),
                name="coin_tx_balance_after_nonneg",
            ),
        ),
        migrations.AddIndex(
            model_name="cointransaction",
            index=models.Index(fields=["user", "created_at"], name="coin_tx_user_created_idx"),
        ),
        migrations.AddIndex(
            model_name="cointransaction",
            index=models.Index(fields=["related_model", "related_id"], name="coin_tx_subject_idx"),
        ),
        migrations.RunPython(seed_coin_wallets, migrations.RunPython.noop),
    ]
