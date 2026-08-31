from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("account_email", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PasswordResetRequest",
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
                ("token_hash", models.CharField(max_length=128, verbose_name="Хеш токена")),
                (
                    "password_fingerprint",
                    models.CharField(max_length=64, verbose_name="Отпечаток пароля"),
                ),
                ("opened_at", models.DateTimeField(blank=True, null=True, verbose_name="Ссылка открыта")),
                ("revoked_at", models.DateTimeField(blank=True, null=True, verbose_name="Отозвано")),
                ("completed_at", models.DateTimeField(blank=True, null=True, verbose_name="Пароль изменён")),
                ("expires_at", models.DateTimeField(verbose_name="Истекает")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создано")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлено")),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="password_reset_requests",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Пользователь",
                    ),
                ),
            ],
            options={
                "verbose_name": "Запрос сброса пароля",
                "verbose_name_plural": "Запросы сброса пароля",
                "ordering": ("-created_at", "-id"),
            },
        ),
        migrations.AddIndex(
            model_name="passwordresetrequest",
            index=models.Index(
                fields=("user", "opened_at", "revoked_at", "completed_at"),
                name="pwd_reset_user_state_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="passwordresetrequest",
            index=models.Index(fields=("expires_at",), name="pwd_reset_expires_idx"),
        ),
    ]
