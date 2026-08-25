from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        READER = "reader", "Пользователь"
        ANALYST = "analyst", "Аналитик"

    role = models.CharField(
        "Роль",
        max_length=16,
        choices=Role.choices,
        default=Role.READER,
        db_index=True,
    )

    @property
    def is_analyst(self) -> bool:
        return self.role == self.Role.ANALYST

    @property
    def is_reader(self) -> bool:
        return self.role == self.Role.READER


class AnalystProfile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="analyst_profile",
        verbose_name="Пользователь",
    )
    display_name = models.CharField("Отображаемое имя", max_length=120, blank=True)
    avatar = models.ImageField(
        "Аватар",
        upload_to="analysts/avatars/%Y/%m/",
        blank=True,
        null=True,
    )
    bio = models.TextField("О себе", max_length=2000, blank=True)
    is_verified = models.BooleanField("Проверен", default=False, db_index=True)
    is_public = models.BooleanField("Публичный профиль", default=True, db_index=True)
    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлён", auto_now=True)

    class Meta:
        verbose_name = "Профиль аналитика"
        verbose_name_plural = "Профили аналитиков"
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return self.display_name or self.user.get_full_name() or self.user.username
