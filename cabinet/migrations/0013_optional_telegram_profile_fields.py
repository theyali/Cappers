from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cabinet", "0012_analystprofile_referral_code"),
    ]

    operations = [
        migrations.AlterField(
            model_name="analystprofile",
            name="telegram_channel",
            field=models.CharField(
                "Telegram канал",
                max_length=160,
                default="",
                blank=True,
            ),
        ),
        migrations.AlterField(
            model_name="analystprofile",
            name="telegram_account",
            field=models.CharField(
                "Telegram аккаунт",
                max_length=160,
                default="",
                blank=True,
            ),
        ),
    ]
