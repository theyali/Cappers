from django.conf import settings
import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="AchievementCategory",
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
                ("title", models.CharField(max_length=120, verbose_name="Название")),
                (
                    "slug",
                    models.SlugField(
                        max_length=120,
                        unique=True,
                        verbose_name="Slug",
                    ),
                ),
                (
                    "description",
                    models.TextField(blank=True, verbose_name="Описание"),
                ),
                (
                    "icon",
                    models.ImageField(
                        blank=True,
                        upload_to="achievements/categories/",
                        verbose_name="Иконка",
                    ),
                ),
                (
                    "color",
                    models.CharField(
                        default="#0b56fa",
                        max_length=16,
                        verbose_name="Цвет",
                    ),
                ),
                (
                    "sort_order",
                    models.PositiveIntegerField(
                        default=0,
                        verbose_name="Порядок",
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(default=True, verbose_name="Активна"),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        verbose_name="Создана",
                    ),
                ),
                (
                    "updated_at",
                    models.DateTimeField(
                        auto_now=True,
                        verbose_name="Обновлена",
                    ),
                ),
            ],
            options={
                "verbose_name": "Категория достижений",
                "verbose_name_plural": "Категории достижений",
                "ordering": ("sort_order", "id"),
            },
        ),
        migrations.CreateModel(
            name="Achievement",
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
                    "key",
                    models.SlugField(
                        max_length=120,
                        unique=True,
                        verbose_name="Ключ",
                    ),
                ),
                (
                    "title",
                    models.CharField(max_length=160, verbose_name="Название"),
                ),
                (
                    "description",
                    models.TextField(blank=True, verbose_name="Описание"),
                ),
                (
                    "short_description",
                    models.CharField(
                        blank=True,
                        max_length=255,
                        verbose_name="Краткое описание",
                    ),
                ),
                (
                    "icon",
                    models.ImageField(
                        blank=True,
                        upload_to="achievements/icons/",
                        verbose_name="Иконка",
                    ),
                ),
                (
                    "fallback_static_icon",
                    models.CharField(
                        blank=True,
                        max_length=255,
                        verbose_name="Статическая иконка",
                    ),
                ),
                (
                    "audience",
                    models.CharField(
                        choices=[
                            ("all", "Все пользователи"),
                            ("reader", "Обычные пользователи"),
                            ("analyst", "Капперы"),
                        ],
                        default="all",
                        max_length=16,
                        verbose_name="Аудитория",
                    ),
                ),
                (
                    "metric",
                    models.CharField(
                        choices=[
                            ("predictions", "Прогнозы"),
                            ("wins", "Победы"),
                            ("roi", "ROI"),
                            ("followers", "Подписчики"),
                            ("streak", "Серия побед"),
                            ("verified", "Верификация"),
                            ("likes_given", "Поставленные лайки"),
                            ("favorites_saved", "Сохранения"),
                            ("referrals", "Рефералы"),
                            ("custom", "Другое"),
                        ],
                        db_index=True,
                        max_length=32,
                        verbose_name="Метрика",
                    ),
                ),
                (
                    "target_value",
                    models.DecimalField(
                        decimal_places=2,
                        default=1,
                        max_digits=14,
                        verbose_name="Целевое значение",
                    ),
                ),
                (
                    "condition_operator",
                    models.CharField(
                        choices=[
                            ("gte", "Больше или равно"),
                            ("lte", "Меньше или равно"),
                            ("eq", "Равно"),
                        ],
                        default="gte",
                        max_length=8,
                        verbose_name="Условие",
                    ),
                ),
                (
                    "is_active",
                    models.BooleanField(default=True, verbose_name="Активно"),
                ),
                (
                    "is_secret",
                    models.BooleanField(default=False, verbose_name="Секретное"),
                ),
                (
                    "show_progress",
                    models.BooleanField(
                        default=True,
                        verbose_name="Показывать прогресс",
                    ),
                ),
                (
                    "coins_reward",
                    models.PositiveIntegerField(
                        default=0,
                        verbose_name="Награда, коинов",
                    ),
                ),
                (
                    "xp_reward",
                    models.PositiveIntegerField(
                        default=0,
                        verbose_name="Награда XP",
                    ),
                ),
                (
                    "sort_order",
                    models.PositiveIntegerField(
                        default=0,
                        verbose_name="Порядок",
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
                    "updated_at",
                    models.DateTimeField(
                        auto_now=True,
                        verbose_name="Обновлено",
                    ),
                ),
                (
                    "category",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="achievements",
                        to="achievements.achievementcategory",
                        verbose_name="Категория",
                    ),
                ),
            ],
            options={
                "verbose_name": "Достижение",
                "verbose_name_plural": "Достижения",
                "ordering": ("sort_order", "id"),
                "indexes": [
                    models.Index(
                        fields=["is_active", "audience", "sort_order"],
                        name="achievement_active_aud_idx",
                    ),
                    models.Index(
                        fields=["metric", "target_value"],
                        name="achievement_metric_target_idx",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="AchievementProgressSnapshot",
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
                    "current_value",
                    models.DecimalField(
                        decimal_places=2,
                        default=0,
                        max_digits=14,
                        verbose_name="Текущее значение",
                    ),
                ),
                (
                    "progress_percent",
                    models.PositiveSmallIntegerField(
                        default=0,
                        verbose_name="Прогресс, %",
                    ),
                ),
                (
                    "updated_at",
                    models.DateTimeField(
                        auto_now=True,
                        verbose_name="Обновлено",
                    ),
                ),
                (
                    "achievement",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="progress_snapshots",
                        to="achievements.achievement",
                        verbose_name="Достижение",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="achievement_progress_snapshots",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Пользователь",
                    ),
                ),
            ],
            options={
                "verbose_name": "Прогресс достижения",
                "verbose_name_plural": "Прогресс достижений",
                "constraints": [
                    models.UniqueConstraint(
                        fields=("user", "achievement"),
                        name="unique_achievement_progress_snapshot",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="UserAchievement",
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
                    "unlocked_at",
                    models.DateTimeField(
                        default=django.utils.timezone.now,
                        verbose_name="Получено",
                    ),
                ),
                (
                    "progress_value",
                    models.DecimalField(
                        decimal_places=2,
                        default=0,
                        max_digits=14,
                        verbose_name="Значение прогресса",
                    ),
                ),
                (
                    "progress_percent",
                    models.PositiveSmallIntegerField(
                        default=100,
                        verbose_name="Прогресс, %",
                    ),
                ),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("auto", "Автоматически"),
                            ("manual", "Вручную"),
                            ("migration", "Миграция"),
                            ("admin", "Администратор"),
                        ],
                        default="auto",
                        max_length=16,
                        verbose_name="Источник",
                    ),
                ),
                (
                    "metadata",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        verbose_name="Метаданные",
                    ),
                ),
                (
                    "achievement",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="user_achievements",
                        to="achievements.achievement",
                        verbose_name="Достижение",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="achievements",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Пользователь",
                    ),
                ),
            ],
            options={
                "verbose_name": "Достижение пользователя",
                "verbose_name_plural": "Достижения пользователей",
                "ordering": ("-unlocked_at", "-id"),
                "indexes": [
                    models.Index(
                        fields=["user", "-unlocked_at"],
                        name="userach_user_unlock_idx",
                    ),
                    models.Index(
                        fields=["achievement", "-unlocked_at"],
                        name="userach_ach_unlock_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("user", "achievement"),
                        name="unique_user_achievement",
                    ),
                ],
            },
        ),
    ]
