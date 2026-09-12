from django.conf import settings
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cabinet", "0027_roulette_models"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserRouletteState",
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
                    "available_spins",
                    models.PositiveIntegerField(default=0, verbose_name="Доступно попыток"),
                ),
                (
                    "next_spin_at",
                    models.DateTimeField(
                        blank=True,
                        db_index=True,
                        null=True,
                        verbose_name="Следующая ежедневная попытка",
                    ),
                ),
                (
                    "last_spin_at",
                    models.DateTimeField(
                        blank=True,
                        db_index=True,
                        null=True,
                        verbose_name="Последняя прокрутка",
                    ),
                ),
                (
                    "total_spins",
                    models.PositiveBigIntegerField(default=0, verbose_name="Всего прокруток"),
                ),
                (
                    "last_daily_grant_at",
                    models.DateTimeField(
                        blank=True,
                        db_index=True,
                        null=True,
                        verbose_name="Последнее ежедневное начисление",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создано")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлено")),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="roulette_state",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Пользователь",
                    ),
                ),
            ],
            options={
                "verbose_name": "Состояние рулетки пользователя",
                "verbose_name_plural": "Состояния рулетки пользователей",
                "ordering": ("user_id",),
                "indexes": [
                    models.Index(
                        fields=["available_spins", "next_spin_at"],
                        name="roulette_state_ready_idx",
                    ),
                ],
            },
        ),
    ]
