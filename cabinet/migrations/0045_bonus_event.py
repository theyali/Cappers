from django.conf import settings
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cabinet", "0044_daily_streaks"),
    ]

    operations = [
        migrations.CreateModel(
            name="BonusEvent",
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
                    "event_type",
                    models.CharField(
                        choices=[
                            ("daily_task", "Ежедневное задание"),
                            ("streak", "Серия дней"),
                            ("roulette", "Рулетка"),
                            ("referral", "Реферальный бонус"),
                        ],
                        max_length=24,
                        verbose_name="Тип события",
                    ),
                ),
                ("title", models.CharField(max_length=160, verbose_name="Название")),
                ("description", models.TextField(blank=True, verbose_name="Описание")),
                ("xp_delta", models.BigIntegerField(default=0, verbose_name="Изменение XP")),
                (
                    "coin_delta",
                    models.BigIntegerField(default=0, verbose_name="Изменение коинов"),
                ),
                (
                    "spin_delta",
                    models.BigIntegerField(default=0, verbose_name="Изменение попыток"),
                ),
                (
                    "related_model",
                    models.CharField(
                        blank=True,
                        max_length=100,
                        verbose_name="Связанная модель",
                    ),
                ),
                (
                    "related_id",
                    models.PositiveBigIntegerField(
                        blank=True,
                        null=True,
                        verbose_name="ID связанного объекта",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        verbose_name="Создано",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="bonus_events",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Пользователь",
                    ),
                ),
            ],
            options={
                "verbose_name": "Бонусное событие",
                "verbose_name_plural": "Бонусные события",
                "ordering": ("-created_at", "-id"),
                "indexes": [
                    models.Index(
                        fields=["user", "created_at"],
                        name="bonus_event_user_time_idx",
                    ),
                    models.Index(
                        fields=["event_type", "created_at"],
                        name="bonus_event_type_time_idx",
                    ),
                    models.Index(
                        fields=["user", "related_model", "related_id", "event_type"],
                        name="bonus_event_related_idx",
                    ),
                ],
            },
        ),
    ]
