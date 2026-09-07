from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("wallets", "0005_copybettingsubscription_active_since_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="realbalancetransaction",
            name="kind",
            field=models.CharField(
                choices=[
                    ("subscription_income", "Доход с подписки"),
                    ("tournament_prize", "Приз турнира"),
                    ("referral_subscription", "Реферал: покупка подписки"),
                    ("referral_tournament", "Реферал: приз турнира"),
                    ("referral_balance_top_up", "Реферал: пополнение баланса"),
                    ("real_deposit", "Реальное пополнение"),
                    ("virtual_top_up", "Пополнение виртуального баланса"),
                    ("withdrawal_request", "Заявка на вывод"),
                    ("withdrawal_cancel", "Отмена вывода"),
                    ("adjustment", "Корректировка"),
                ],
                db_index=True,
                max_length=32,
                verbose_name="Тип",
            ),
        ),
    ]
