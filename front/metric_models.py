from django.conf import settings
from django.db import models
from django.utils import timezone


class PredictionMetrics(models.Model):
    coupon = models.OneToOneField(
        "game.PredictionCoupon",
        on_delete=models.CASCADE,
        related_name="metrics",
        verbose_name="Прогноз",
    )
    likes_count = models.PositiveIntegerField("Лайки", default=0)
    comments_count = models.PositiveIntegerField("Комментарии", default=0)
    favorites_count = models.PositiveIntegerField("Избранное", default=0)
    views_count = models.PositiveIntegerField("Просмотры", default=0)
    unique_opens_count = models.PositiveIntegerField("Уникальные открытия", default=0)
    unique_opens_started_at = models.DateTimeField("Начало сбора открытий", default=timezone.now)
    shares_count = models.PositiveIntegerField("Репосты", default=0)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        verbose_name = "Метрики прогноза"
        verbose_name_plural = "Метрики прогнозов"

    def __str__(self) -> str:
        return f"Метрики прогноза #{self.coupon_id}"


class PredictionCouponOpen(models.Model):
    coupon = models.ForeignKey("game.PredictionCoupon", on_delete=models.CASCADE, related_name="unique_opens")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="coupon_opens",
    )
    first_opened_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["coupon", "user"], name="unique_coupon_open_user"),
        ]
        indexes = [models.Index(fields=["coupon", "first_opened_at"], name="coupon_open_date_idx")]


class MatchMetrics(models.Model):
    match = models.OneToOneField(
        "game.Match",
        on_delete=models.CASCADE,
        related_name="metrics",
        verbose_name="Матч",
    )
    predictions_count = models.PositiveIntegerField("Прогнозы", default=0)
    comments_count = models.PositiveIntegerField("Комментарии", default=0)
    favorites_count = models.PositiveIntegerField("Избранное", default=0)
    views_count = models.PositiveIntegerField("Просмотры", default=0)
    shares_count = models.PositiveIntegerField("Репосты", default=0)
    activity_count = models.PositiveIntegerField("Активность", default=0)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        verbose_name = "Метрики матча"
        verbose_name_plural = "Метрики матчей"

    def __str__(self) -> str:
        return f"Метрики матча #{self.match_id}"
