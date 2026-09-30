from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("account_email", "0002_passwordresetrequest"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="EmailVerificationRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("email", models.EmailField(max_length=254, verbose_name="Почта")),
                ("token_hash", models.CharField(max_length=128, verbose_name="Хеш токена")),
                ("completed_at", models.DateTimeField(blank=True, null=True, verbose_name="Подтверждено")),
                ("revoked_at", models.DateTimeField(blank=True, null=True, verbose_name="Отозвано")),
                ("expires_at", models.DateTimeField(verbose_name="Истекает")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создано")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлено")),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="email_verification_requests",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Пользователь",
                    ),
                ),
            ],
            options={
                "verbose_name": "Подтверждение почты",
                "verbose_name_plural": "Подтверждения почты",
                "ordering": ("-created_at", "-id"),
            },
        ),
        migrations.AddIndex(
            model_name="emailverificationrequest",
            index=models.Index(
                fields=["user", "completed_at", "revoked_at", "expires_at"],
                name="email_verify_user_state_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="emailverificationrequest",
            index=models.Index(fields=["email"], name="email_verify_email_idx"),
        ),
    ]
