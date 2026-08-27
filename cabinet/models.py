import re

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
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
    avatar = models.ImageField(
        "Аватар",
        upload_to="users/avatars/%Y/%m/",
        blank=True,
        null=True,
    )
    telegram_id = models.BigIntegerField(
        "Telegram ID",
        blank=True,
        null=True,
        unique=True,
    )
    telegram_username = models.CharField(
        "Telegram username",
        max_length=150,
        blank=True,
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
    specialization = models.CharField("Специализация", max_length=220, blank=True)
    favorite_sports = models.CharField("Любимые виды спорта", max_length=320, blank=True)
    favorite_leagues = models.CharField("Любимые лиги", max_length=500, blank=True)
    telegram_channel = models.CharField("Telegram канал", max_length=160, default="")
    telegram_account = models.CharField("Telegram аккаунт", max_length=160, default="")
    instagram = models.CharField("Instagram", max_length=160, blank=True)
    threads = models.CharField("Threads", max_length=160, blank=True)
    youtube = models.CharField("YouTube канал", max_length=200, blank=True)
    tiktok = models.CharField("TikTok", max_length=160, blank=True)
    facebook = models.CharField("Facebook", max_length=200, blank=True)
    is_verified = models.BooleanField("Проверен", default=False, db_index=True)
    is_public = models.BooleanField("Публичный профиль", default=True, db_index=True)
    onboarding_completed_at = models.DateTimeField("Onboarding завершён", null=True, blank=True)
    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлён", auto_now=True)

    class Meta:
        verbose_name = "Профиль аналитика"
        verbose_name_plural = "Профили аналитиков"
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return self.display_name or self.user.get_full_name() or self.user.username

    def clean(self) -> None:
        super().clean()

    @property
    def social_links(self) -> list[dict]:
        values = [
            ("telegram_channel", "Telegram канал", self.telegram_channel, "telegram"),
            ("telegram_account", "Telegram аккаунт", self.telegram_account, "telegram"),
            ("instagram", "Instagram", self.instagram, "instagram"),
            ("threads", "Threads", self.threads, "threads"),
            ("youtube", "YouTube", self.youtube, "youtube"),
            ("tiktok", "TikTok", self.tiktok, "tiktok"),
            ("facebook", "Facebook", self.facebook, "facebook"),
        ]
        return [
            {"key": key, "label": label, "value": value, "url": _social_url(value, network)}
            for key, label, value, network in values
            if (value or "").strip()
        ]


def _social_url(value: str, network: str) -> str:
    text = (value or "").strip()
    if not text:
        return "#"
    if text.startswith(("http://", "https://")):
        return text

    handle = re.sub(r"^@", "", text).strip("/")
    if network == "telegram":
        return f"https://t.me/{handle}"
    if network == "instagram":
        return f"https://www.instagram.com/{handle}"
    if network == "threads":
        return f"https://www.threads.net/@{handle}"
    if network == "youtube":
        if handle.startswith("@"):
            return f"https://www.youtube.com/{handle}"
        return f"https://www.youtube.com/@{handle}"
    if network == "tiktok":
        return f"https://www.tiktok.com/@{handle}"
    if network == "facebook":
        return f"https://www.facebook.com/{handle}"
    return text


class AnalystFollow(models.Model):
    follower = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="analyst_follows",
        verbose_name="Подписчик",
    )
    analyst = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="analyst_followers",
        verbose_name="Аналитик",
    )
    created_at = models.DateTimeField("Дата подписки", auto_now_add=True)

    class Meta:
        verbose_name = "Подписка на аналитика"
        verbose_name_plural = "Подписки на аналитиков"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("follower", "analyst"),
                name="unique_analyst_follow",
            )
        ]
        indexes = [
            models.Index(fields=("analyst", "created_at"), name="follow_analyst_created_idx"),
            models.Index(fields=("follower", "created_at"), name="follow_follower_created_idx"),
        ]

    def clean(self) -> None:
        if self.follower_id and self.analyst_id and self.follower_id == self.analyst_id:
            raise ValidationError("Нельзя подписаться на самого себя.")
        if self.analyst_id and self.analyst.role != User.Role.ANALYST:
            raise ValidationError("Подписываться можно только на аналитиков.")

    def __str__(self) -> str:
        return f"{self.follower} → {self.analyst}"
