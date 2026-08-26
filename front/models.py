from django.conf import settings
from django.db import models

from game.models import Prediction


class PredictionLike(models.Model):
    prediction = models.ForeignKey(
        Prediction,
        on_delete=models.CASCADE,
        related_name="likes",
        verbose_name="Прогноз",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="prediction_likes",
        verbose_name="Пользователь",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("prediction", "user"),
                name="unique_prediction_like",
            )
        ]
        indexes = [
            models.Index(fields=("prediction", "created_at"), name="pred_like_pred_created_idx"),
            models.Index(fields=("user", "created_at"), name="pred_like_user_created_idx"),
        ]
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.user} 👍 {self.prediction_id}"


class PredictionFavorite(models.Model):
    prediction = models.ForeignKey(
        Prediction,
        on_delete=models.CASCADE,
        related_name="favorites",
        verbose_name="Прогноз",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="prediction_favorites",
        verbose_name="Пользователь",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("prediction", "user"),
                name="unique_prediction_favorite",
            )
        ]
        indexes = [
            models.Index(fields=("user", "created_at"), name="pred_fav_user_created_idx"),
        ]
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.user} ♥ {self.prediction_id}"
