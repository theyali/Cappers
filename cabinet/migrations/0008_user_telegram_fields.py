from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cabinet", "0007_user_avatar"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="telegram_id",
            field=models.BigIntegerField(
                blank=True,
                null=True,
                unique=True,
                verbose_name="Telegram ID",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="telegram_username",
            field=models.CharField(
                blank=True,
                max_length=150,
                verbose_name="Telegram username",
            ),
        ),
    ]
