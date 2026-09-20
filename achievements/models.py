from django.conf import settings
from django.db import models
from django.utils import timezone


class AchievementCategory(models.Model):
    title = models.CharField("Название", max_length=120)
    slug = models.SlugField("Slug", max_length=120, unique=True)
    description = models.TextField("Описание", blank=True)
    icon = models.ImageField(
        "Иконка",
        upload_to="achievements/categories/",
        blank=True,
    )
    color = models.CharField("Цвет", max_length=16, default="#0b56fa")
    sort_order = models.PositiveIntegerField("Порядок", default=0)
    is_active = models.BooleanField("Активна", default=True)
    created_at = models.DateTimeField("Создана", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлена", auto_now=True)

    class Meta:
        verbose_name = "Категория достижений"
        verbose_name_plural = "Категории достижений"
        ordering = ("sort_order", "id")

    def __str__(self) -> str:
        return self.title


class Achievement(models.Model):
    class Audience(models.TextChoices):
        ALL = "all", "Все пользователи"
        READER = "reader", "Обычные пользователи"
        ANALYST = "analyst", "Капперы"

    class Metric(models.TextChoices):
        PREDICTIONS = "predictions", "Прогнозы"
        WINS = "wins", "Победы"
        ROI = "roi", "ROI"
        FOLLOWERS = "followers", "Подписчики"
        STREAK = "streak", "Серия побед"
        VERIFIED = "verified", "Верификация"
        LIKES_GIVEN = "likes_given", "Поставленные лайки"
        FAVORITES_SAVED = "favorites_saved", "Сохранения"
        REFERRALS = "referrals", "Рефералы"
        CUSTOM = "custom", "Другое"

    class ConditionOperator(models.TextChoices):
        GTE = "gte", "Больше или равно"
        LTE = "lte", "Меньше или равно"
        EQ = "eq", "Равно"

    category = models.ForeignKey(
        AchievementCategory,
        on_delete=models.PROTECT,
        related_name="achievements",
        verbose_name="Категория",
    )
    key = models.SlugField("Ключ", max_length=120, unique=True)
    title = models.CharField("Название", max_length=160)
    description = models.TextField("Описание", blank=True)
    short_description = models.CharField(
        "Краткое описание",
        max_length=255,
        blank=True,
    )
    icon = models.ImageField(
        "Иконка",
        upload_to="achievements/icons/",
        blank=True,
    )
    fallback_static_icon = models.CharField(
        "Статическая иконка",
        max_length=255,
        blank=True,
    )
    audience = models.CharField(
        "Аудитория",
        max_length=16,
        choices=Audience.choices,
        default=Audience.ALL,
    )
    metric = models.CharField(
        "Метрика",
        max_length=32,
        choices=Metric.choices,
        db_index=True,
    )
    target_value = models.DecimalField(
        "Целевое значение",
        max_digits=14,
        decimal_places=2,
        default=1,
    )
    condition_operator = models.CharField(
        "Условие",
        max_length=8,
        choices=ConditionOperator.choices,
        default=ConditionOperator.GTE,
    )
    is_active = models.BooleanField("Активно", default=True)
    is_secret = models.BooleanField("Секретное", default=False)
    show_progress = models.BooleanField("Показывать прогресс", default=True)
    coins_reward = models.PositiveIntegerField("Награда, коинов", default=0)
    xp_reward = models.PositiveIntegerField("Награда XP", default=0)
    sort_order = models.PositiveIntegerField("Порядок", default=0)
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        verbose_name = "Достижение"
        verbose_name_plural = "Достижения"
        ordering = ("sort_order", "id")
        indexes = [
            models.Index(
                fields=("is_active", "audience", "sort_order"),
                name="achievement_active_aud_idx",
            ),
            models.Index(
                fields=("metric", "target_value"),
                name="achievement_metric_target_idx",
            ),
        ]

    def __str__(self) -> str:
        return self.title


class UserAchievement(models.Model):
    class Source(models.TextChoices):
        AUTO = "auto", "Автоматически"
        MANUAL = "manual", "Вручную"
        MIGRATION = "migration", "Миграция"
        ADMIN = "admin", "Администратор"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="achievements",
        verbose_name="Пользователь",
    )
    achievement = models.ForeignKey(
        Achievement,
        on_delete=models.CASCADE,
        related_name="user_achievements",
        verbose_name="Достижение",
    )
    unlocked_at = models.DateTimeField("Получено", default=timezone.now)
    progress_value = models.DecimalField(
        "Значение прогресса",
        max_digits=14,
        decimal_places=2,
        default=0,
    )
    progress_percent = models.PositiveSmallIntegerField(
        "Прогресс, %",
        default=100,
    )
    source = models.CharField(
        "Источник",
        max_length=16,
        choices=Source.choices,
        default=Source.AUTO,
    )
    metadata = models.JSONField("Метаданные", default=dict, blank=True)

    class Meta:
        verbose_name = "Достижение пользователя"
        verbose_name_plural = "Достижения пользователей"
        ordering = ("-unlocked_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("user", "achievement"),
                name="unique_user_achievement",
            ),
        ]
        indexes = [
            models.Index(
                fields=("user", "-unlocked_at"),
                name="userach_user_unlock_idx",
            ),
            models.Index(
                fields=("achievement", "-unlocked_at"),
                name="userach_ach_unlock_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user}: {self.achievement}"


class AchievementProgressSnapshot(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="achievement_progress_snapshots",
        verbose_name="Пользователь",
    )
    achievement = models.ForeignKey(
        Achievement,
        on_delete=models.CASCADE,
        related_name="progress_snapshots",
        verbose_name="Достижение",
    )
    current_value = models.DecimalField(
        "Текущее значение",
        max_digits=14,
        decimal_places=2,
        default=0,
    )
    progress_percent = models.PositiveSmallIntegerField(
        "Прогресс, %",
        default=0,
    )
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        verbose_name = "Прогресс достижения"
        verbose_name_plural = "Прогресс достижений"
        constraints = [
            models.UniqueConstraint(
                fields=("user", "achievement"),
                name="unique_achievement_progress_snapshot",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user}: {self.achievement} — {self.progress_percent}%"
