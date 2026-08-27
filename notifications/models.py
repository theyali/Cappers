from django.conf import settings
from django.db import models
from django.utils import timezone

from game.models import Match, PredictionCoupon


class NotificationPreference(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_preferences",
        verbose_name="Пользователь",
    )
    in_app_enabled = models.BooleanField("На сайте", default=True)
    email_enabled = models.BooleanField("Email", default=False)
    telegram_enabled = models.BooleanField("Telegram", default=False)
    telegram_chat_id = models.CharField("Telegram chat id", max_length=80, blank=True, db_index=True)
    telegram_username = models.CharField("Telegram username", max_length=80, blank=True)
    telegram_connected_at = models.DateTimeField("Telegram подключён", null=True, blank=True)

    new_prediction = models.BooleanField("Новые прогнозы капперов", default=True)
    favorite_settled = models.BooleanField("Расчёт избранных прогнозов", default=True)
    match_reminder = models.BooleanField("Напоминания о матчах", default=True)
    achievement = models.BooleanField("Достижения капперов", default=True)
    match_prediction = models.BooleanField("Прогнозы на отслеживаемые матчи", default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Настройки уведомлений"
        verbose_name_plural = "Настройки уведомлений"

    def __str__(self) -> str:
        return f"Уведомления: {self.user}"


class TelegramAccount(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="telegram_account",
        verbose_name="Пользователь",
    )
    chat_id = models.CharField("Telegram chat id", max_length=80, unique=True, db_index=True)
    username = models.CharField("Telegram username", max_length=80, blank=True)
    first_name = models.CharField("Имя в Telegram", max_length=120, blank=True)
    last_name = models.CharField("Фамилия в Telegram", max_length=120, blank=True)
    language_code = models.CharField("Язык Telegram", max_length=12, blank=True)
    connected_at = models.DateTimeField("Подключён", default=timezone.now)
    last_seen_at = models.DateTimeField("Последняя активность", default=timezone.now)

    class Meta:
        verbose_name = "Telegram-аккаунт"
        verbose_name_plural = "Telegram-аккаунты"
        ordering = ("-connected_at",)

    def __str__(self) -> str:
        username = f"@{self.username}" if self.username else self.chat_id
        return f"{self.user} → {username}"


class TelegramLinkToken(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="telegram_link_tokens",
        verbose_name="Пользователь",
    )
    token_hash = models.CharField("Хеш токена", max_length=64, unique=True)
    expires_at = models.DateTimeField("Истекает")
    used_at = models.DateTimeField("Использован", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Токен привязки Telegram"
        verbose_name_plural = "Токены привязки Telegram"
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("expires_at", "used_at"), name="notif_tg_link_exp_idx")]

    def __str__(self) -> str:
        return f"Telegram link: {self.user}"

    @property
    def is_active(self) -> bool:
        return self.used_at is None and self.expires_at > timezone.now()


class Notification(models.Model):
    class Kind(models.TextChoices):
        NEW_PREDICTION = "new_prediction", "Новый прогноз"
        FAVORITE_SETTLED = "favorite_settled", "Избранный прогноз рассчитан"
        MATCH_REMINDER = "match_reminder", "Скоро матч"
        ACHIEVEMENT = "achievement", "Достижение каппера"
        MATCH_PREDICTION = "match_prediction", "Прогноз на отслеживаемый матч"

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name="Получатель",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="notification_actions",
        verbose_name="Инициатор",
        null=True,
        blank=True,
    )
    kind = models.CharField("Тип", max_length=32, choices=Kind.choices, db_index=True)
    title = models.CharField("Заголовок", max_length=180)
    message = models.TextField("Текст", max_length=1000, blank=True)
    url = models.CharField("Ссылка", max_length=500, blank=True)
    event_key = models.CharField("Ключ события", max_length=255, unique=True)
    meta = models.JSONField("Данные", default=dict, blank=True)

    show_in_app = models.BooleanField("Показывать на сайте", default=True, db_index=True)
    is_read = models.BooleanField("Прочитано", default=False, db_index=True)
    read_at = models.DateTimeField("Прочитано в", null=True, blank=True)

    email_processed_at = models.DateTimeField(null=True, blank=True)
    email_sent_at = models.DateTimeField(null=True, blank=True)
    telegram_processed_at = models.DateTimeField(null=True, blank=True)
    telegram_sent_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField("Создано", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Уведомление"
        verbose_name_plural = "Уведомления"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("recipient", "show_in_app", "is_read", "created_at"), name="notif_recipient_state_idx"),
            models.Index(fields=("kind", "created_at"), name="notif_kind_created_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.recipient}: {self.title}"

    def mark_read(self) -> None:
        if self.is_read:
            return
        self.is_read = True
        self.read_at = timezone.now()
        self.save(update_fields=["is_read", "read_at"])


class MatchWatch(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_match_watches",
        verbose_name="Пользователь",
    )
    match = models.ForeignKey(
        Match,
        on_delete=models.CASCADE,
        related_name="notification_watchers",
        verbose_name="Матч",
    )
    last_scope = models.CharField("Последний статус", max_length=16, blank=True, default="")
    last_score = models.CharField("Последний счёт", max_length=32, blank=True, default="")
    last_time_status = models.CharField("Последний time status", max_length=8, blank=True, default="")
    started_sent_at = models.DateTimeField("Уведомление о старте", null=True, blank=True)
    halftime_sent_at = models.DateTimeField("Уведомление о перерыве", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Отслеживаемый матч"
        verbose_name_plural = "Отслеживаемые матчи"
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(fields=("user", "match"), name="unique_notification_match_watch"),
        ]
        indexes = [
            models.Index(fields=("match", "created_at"), name="notif_watch_match_idx"),
            models.Index(fields=("user", "created_at"), name="notif_watch_user_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.user} → {self.match}"


class AchievementState(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_achievement_state",
        verbose_name="Каппер",
    )
    unlocked_keys = models.JSONField("Полученные достижения", default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Состояние достижений для уведомлений"
        verbose_name_plural = "Состояния достижений капперов"

    def __str__(self) -> str:
        return f"Достижения: {self.user}"


class CouponEventState(models.Model):
    coupon = models.OneToOneField(
        PredictionCoupon,
        on_delete=models.CASCADE,
        related_name="notification_event_state",
        verbose_name="Прогноз",
    )
    published_dispatched_at = models.DateTimeField(null=True, blank=True)
    settled_state = models.CharField(max_length=16, blank=True)
    settled_dispatched_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Состояние событий прогноза"
        verbose_name_plural = "Состояния событий прогнозов"

    def __str__(self) -> str:
        return f"События прогноза #{self.coupon_id}"
