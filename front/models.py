from django.conf import settings
from django.db import models
from django.urls import reverse
from tinymce.models import HTMLField

from game.models import Prediction


class Article(models.Model):
    title = models.CharField("Заголовок", max_length=220)
    slug = models.SlugField("Slug", max_length=240, unique=True)
    description = models.TextField("Краткое описание", max_length=700)
    image = models.ImageField("Изображение", upload_to="articles/%Y/%m/", blank=True, null=True)
    content = HTMLField("Контент")
    is_published = models.BooleanField("Опубликована", default=True, db_index=True)
    created_at = models.DateTimeField("Создана", auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField("Обновлена", auto_now=True)

    class Meta:
        verbose_name = "Статья"
        verbose_name_plural = "Статьи"
        ordering = ("-created_at", "-id")

    def __str__(self) -> str:
        return self.title

    def get_absolute_url(self) -> str:
        return reverse("front:article_detail", kwargs={"slug": self.slug})


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
