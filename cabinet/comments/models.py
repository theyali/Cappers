from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class Comment(models.Model):
    class Status(models.TextChoices):
        PUBLISHED = "published", "Опубликован"
        PENDING = "pending", "На модерации"
        REJECTED = "rejected", "Отклонён"
        DELETED = "deleted", "Удалён"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="comments",
        verbose_name="Пользователь",
    )
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        related_name="+",
        verbose_name="Тип объекта",
    )
    object_id = models.PositiveBigIntegerField(verbose_name="ID объекта")
    target = GenericForeignKey("content_type", "object_id")
    text = models.TextField(max_length=1000, verbose_name="Комментарий")
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PUBLISHED,
        verbose_name="Статус",
    )
    moderation_reason = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Причина модерации",
    )
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="replies",
        verbose_name="Родительский комментарий",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Создан")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Обновлён")

    class Meta:
        ordering = ("created_at", "id")
        verbose_name = "Комментарий"
        verbose_name_plural = "Комментарии"
        indexes = [
            models.Index(
                fields=("content_type", "object_id", "status", "created_at"),
                name="comment_target_status_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Комментарий #{self.pk or 'new'} пользователя {self.user_id}"
