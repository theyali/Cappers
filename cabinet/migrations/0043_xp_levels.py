from django.conf import settings
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cabinet", "0042_daily_tasks"),
    ]

    operations = [
        migrations.CreateModel(
            name="XpLevel",
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
                ("level", models.PositiveIntegerField(unique=True, verbose_name="Уровень")),
                ("title", models.CharField(max_length=80, verbose_name="Название")),
                (
                    "required_xp",
                    models.PositiveBigIntegerField(default=0, verbose_name="Требуется XP"),
                ),
                (
                    "reward_coins",
                    models.PositiveIntegerField(default=0, verbose_name="Награда, коинов"),
                ),
                (
                    "reward_spins",
                    models.PositiveIntegerField(default=0, verbose_name="Награда, попыток"),
                ),
                (
                    "is_active",
                    models.BooleanField(db_index=True, default=True, verbose_name="Активен"),
                ),
                ("order", models.PositiveIntegerField(default=0, verbose_name="Порядок")),
            ],
            options={
                "verbose_name": "XP-уровень",
                "verbose_name_plural": "XP-уровни",
                "ordering": ("order", "level", "id"),
                "constraints": [
                    models.CheckConstraint(
                        check=models.Q(("level__gt", 0)),
                        name="xp_level_number_positive",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="UserXpState",
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
                ("level", models.PositiveIntegerField(default=1, verbose_name="Уровень")),
                ("xp", models.PositiveBigIntegerField(default=0, verbose_name="XP")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создано")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлено")),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="xp_state",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Пользователь",
                    ),
                ),
            ],
            options={
                "verbose_name": "XP пользователя",
                "verbose_name_plural": "XP пользователей",
                "ordering": ("-xp", "id"),
                "constraints": [
                    models.CheckConstraint(
                        check=models.Q(("level__gt", 0)),
                        name="user_xp_level_positive",
                    ),
                ],
            },
        ),
    ]
