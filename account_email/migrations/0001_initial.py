from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="EmailChangeRequest",
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
                    "purpose",
                    models.CharField(
                        choices=[
                            ("add", "Добавление почты"),
                            ("change", "Смена почты"),
                        ],
                        max_length=16,
                        verbose_name="Сценарий",
                    ),
                ),
                ("current_email", models.EmailField(blank=True, max_length=254, verbose_name="Текущая почта")),
                ("new_email", models.EmailField(blank=True, max_length=254, verbose_name="Новая почта")),
                (
                    "current_token",
                    models.CharField(
                        blank=True,
                        max_length=96,
                        null=True,
                        unique=True,
                        verbose_name="Токен подтверждения текущей почты",
                    ),
                ),
                ("code_hash", models.CharField(blank=True, max_length=128, verbose_name="Хеш кода новой почты")),
                (
                    "current_confirmed_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                        verbose_name="Текущая почта подтверждена",
                    ),
                ),
                (
                    "new_code_sent_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                        verbose_name="Код на новую почту отправлен",
                    ),
                ),
                ("completed_at", models.DateTimeField(blank=True, null=True, verbose_name="Завершено")),
                ("expires_at", models.DateTimeField(verbose_name="Истекает")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создано")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлено")),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="email_change_requests",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Пользователь",
                    ),
                ),
            ],
            options={
                "verbose_name": "Запрос смены почты",
                "verbose_name_plural": "Запросы смены почты",
                "ordering": ("-created_at", "-id"),
            },
        ),
        migrations.AddIndex(
            model_name="emailchangerequest",
            index=models.Index(
                fields=("user", "completed_at", "expires_at"),
                name="email_req_user_state_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="emailchangerequest",
            index=models.Index(fields=("new_email",), name="email_req_new_email_idx"),
        ),
    ]
