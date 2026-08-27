from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="notificationpreference",
            name="telegram_chat_id",
            field=models.CharField(blank=True, db_index=True, max_length=80, verbose_name="Telegram chat id"),
        ),
        migrations.AddField(
            model_name="notificationpreference",
            name="telegram_connected_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Telegram подключён"),
        ),
        migrations.AddField(
            model_name="notificationpreference",
            name="telegram_username",
            field=models.CharField(blank=True, max_length=80, verbose_name="Telegram username"),
        ),
        migrations.CreateModel(
            name="TelegramLinkToken",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("token_hash", models.CharField(max_length=64, unique=True, verbose_name="Хеш токена")),
                ("expires_at", models.DateTimeField(verbose_name="Истекает")),
                ("used_at", models.DateTimeField(blank=True, null=True, verbose_name="Использован")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="telegram_link_tokens", to=settings.AUTH_USER_MODEL, verbose_name="Пользователь")),
            ],
            options={
                "verbose_name": "Токен привязки Telegram",
                "verbose_name_plural": "Токены привязки Telegram",
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddIndex(
            model_name="telegramlinktoken",
            index=models.Index(fields=["expires_at", "used_at"], name="notif_tg_link_exp_idx"),
        ),
    ]
