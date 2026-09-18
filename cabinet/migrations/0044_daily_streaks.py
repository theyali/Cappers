from django.conf import settings
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cabinet", "0043_xp_levels"),
    ]

    operations = [
        migrations.CreateModel(
            name="StreakReward",
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
                    "day_number",
                    models.PositiveIntegerField(unique=True, verbose_name="День серии"),
                ),
                (
                    "reward_xp",
                    models.PositiveIntegerField(default=0, verbose_name="Награда XP"),
                ),
                (
                    "reward_coins",
                    models.PositiveIntegerField(default=0, verbose_name="Награда, коинов"),
                ),
                (
                    "reward_spins",
                    models.PositiveIntegerField(default=0, verbose_name="Награда, попыток"),
                ),
                ("title", models.CharField(max_length=120, verbose_name="Название")),
                (
                    "is_active",
                    models.BooleanField(db_index=True, default=True, verbose_name="Активна"),
                ),
            ],
            options={
                "verbose_name": "Награда за серию дней",
                "verbose_name_plural": "Награды за серию дней",
                "ordering": ("day_number", "id"),
                "constraints": [
                    models.CheckConstraint(
                        check=models.Q(("day_number__gt", 0)),
                        name="streak_reward_day_positive",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="UserDailyStreak",
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
                    "current_days",
                    models.PositiveIntegerField(default=0, verbose_name="Текущая серия, дней"),
                ),
                (
                    "best_days",
                    models.PositiveIntegerField(default=0, verbose_name="Лучшая серия, дней"),
                ),
                (
                    "last_seen_date",
                    models.DateField(blank=True, null=True, verbose_name="Последний активный день"),
                ),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлено")),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="daily_streak",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Пользователь",
                    ),
                ),
            ],
            options={
                "verbose_name": "Серия дней пользователя",
                "verbose_name_plural": "Серии дней пользователей",
                "ordering": ("-current_days", "-best_days", "id"),
            },
        ),
    ]
