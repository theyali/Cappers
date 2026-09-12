from django.conf import settings
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cabinet", "0029_roulettespin"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserRouletteRewardState",
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
                    "vip_until",
                    models.DateTimeField(
                        blank=True,
                        db_index=True,
                        null=True,
                        verbose_name="VIP до",
                    ),
                ),
                (
                    "free_predictions",
                    models.PositiveIntegerField(default=0, verbose_name="Бесплатных прогнозов"),
                ),
                (
                    "rating_boost",
                    models.DecimalField(
                        decimal_places=2,
                        default=0,
                        max_digits=12,
                        verbose_name="Буст рейтинга",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создано")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлено")),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="roulette_rewards",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Пользователь",
                    ),
                ),
            ],
            options={
                "verbose_name": "Награды рулетки пользователя",
                "verbose_name_plural": "Награды рулетки пользователей",
                "ordering": ("user_id",),
            },
        ),
    ]
