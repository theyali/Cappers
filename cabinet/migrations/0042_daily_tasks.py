from django.conf import settings
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cabinet", "0041_migrate_legacy_vip_subscriptions"),
    ]

    operations = [
        migrations.CreateModel(
            name="DailyTask",
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
                ("title", models.CharField(max_length=160, verbose_name="Название")),
                ("description", models.TextField(blank=True, verbose_name="Описание")),
                (
                    "audience",
                    models.CharField(
                        choices=[
                            ("all", "Все пользователи"),
                            ("reader", "Обычные пользователи"),
                            ("capper", "Капперы"),
                        ],
                        default="all",
                        max_length=16,
                        verbose_name="Аудитория",
                    ),
                ),
                (
                    "task_type",
                    models.CharField(
                        choices=[
                            ("daily_login", "Ежедневный вход"),
                            ("spin_roulette", "Прокрутить рулетку"),
                            ("open_feed", "Открыть ленту"),
                            ("view_prediction", "Посмотреть прогноз"),
                            ("add_favorite", "Добавить в избранное"),
                            ("follow_capper", "Подписаться на каппера"),
                            ("create_prediction", "Создать прогноз"),
                            ("publish_prediction", "Опубликовать прогноз"),
                            ("answer_comment", "Ответить на комментарий"),
                            ("update_profile", "Обновить профиль"),
                        ],
                        db_index=True,
                        max_length=32,
                        verbose_name="Тип задания",
                    ),
                ),
                (
                    "target_value",
                    models.PositiveIntegerField(default=1, verbose_name="Целевое значение"),
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
                ("is_active", models.BooleanField(default=True, verbose_name="Активно")),
                ("order", models.PositiveIntegerField(default=0, verbose_name="Порядок")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создано")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлено")),
            ],
            options={
                "verbose_name": "Ежедневное задание",
                "verbose_name_plural": "Ежедневные задания",
                "ordering": ("order", "id"),
                "indexes": [
                    models.Index(
                        fields=["is_active", "audience", "order"],
                        name="dailytask_active_aud_idx",
                    ),
                ],
                "constraints": [
                    models.CheckConstraint(
                        check=models.Q(("target_value__gt", 0)),
                        name="daily_task_target_positive",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="UserDailyTaskProgress",
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
                ("progress_date", models.DateField(verbose_name="Дата прогресса")),
                (
                    "current_value",
                    models.PositiveIntegerField(default=0, verbose_name="Текущее значение"),
                ),
                ("is_completed", models.BooleanField(default=False, verbose_name="Выполнено")),
                (
                    "completed_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                        verbose_name="Выполнено в",
                    ),
                ),
                (
                    "reward_claimed_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                        verbose_name="Награда получена в",
                    ),
                ),
                (
                    "task",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="user_progress",
                        to="cabinet.dailytask",
                        verbose_name="Задание",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="daily_task_progress",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Пользователь",
                    ),
                ),
            ],
            options={
                "verbose_name": "Прогресс ежедневного задания",
                "verbose_name_plural": "Прогресс ежедневных заданий",
                "ordering": ("-progress_date", "task_id"),
                "indexes": [
                    models.Index(
                        fields=["user", "progress_date"],
                        name="dayprog_user_date_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("user", "task", "progress_date"),
                        name="unique_user_daily_task_progress",
                    ),
                ],
            },
        ),
    ]
