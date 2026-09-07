from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("back", "0008_bonus_image"),
    ]

    operations = [
        migrations.AddField(
            model_name="websitesettings",
            name="referral_subscription_percent",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                max_digits=5,
                validators=[MinValueValidator(0), MaxValueValidator(100)],
                verbose_name="Реферал — покупка подписки, %",
            ),
        ),
        migrations.AddField(
            model_name="websitesettings",
            name="referral_tournament_percent",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                max_digits=5,
                validators=[MinValueValidator(0), MaxValueValidator(100)],
                verbose_name="Реферал — приз турнира, %",
            ),
        ),
        migrations.AddField(
            model_name="websitesettings",
            name="referral_balance_topup_percent",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                max_digits=5,
                validators=[MinValueValidator(0), MaxValueValidator(100)],
                verbose_name="Реферал — пополнение баланса, %",
            ),
        ),
        migrations.AddField(
            model_name="websitesettings",
            name="platform_fee_1_day_percent",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                max_digits=5,
                validators=[MinValueValidator(0), MaxValueValidator(100)],
                verbose_name="Комиссия тарифа 1 день, %",
            ),
        ),
        migrations.AddField(
            model_name="websitesettings",
            name="platform_fee_7_days_percent",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                max_digits=5,
                validators=[MinValueValidator(0), MaxValueValidator(100)],
                verbose_name="Комиссия тарифа 7 дней, %",
            ),
        ),
        migrations.AddField(
            model_name="websitesettings",
            name="platform_fee_30_days_percent",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                max_digits=5,
                validators=[MinValueValidator(0), MaxValueValidator(100)],
                verbose_name="Комиссия тарифа 30 дней, %",
            ),
        ),
        migrations.AddField(
            model_name="websitesettings",
            name="platform_fee_90_days_percent",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                max_digits=5,
                validators=[MinValueValidator(0), MaxValueValidator(100)],
                verbose_name="Комиссия тарифа 3 месяца, %",
            ),
        ),
        migrations.AddField(
            model_name="websitesettings",
            name="platform_fee_180_days_percent",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                max_digits=5,
                validators=[MinValueValidator(0), MaxValueValidator(100)],
                verbose_name="Комиссия тарифа 6 месяцев, %",
            ),
        ),
    ]
