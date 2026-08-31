import re
import secrets
from datetime import timedelta

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


REFERRAL_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_referral_code() -> str:
    return "".join(secrets.choice(REFERRAL_CODE_ALPHABET) for _ in range(8))


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
    referral_code = models.CharField(
        "Реферальный код",
        max_length=8,
        unique=True,
        default=generate_referral_code,
        editable=False,
    )
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
    telegram_channel = models.CharField(
        "Telegram канал",
        max_length=160,
        default="",
        blank=True,
    )
    telegram_account = models.CharField(
        "Telegram аккаунт",
        max_length=160,
        default="",
        blank=True,
    )
    instagram = models.CharField("Instagram", max_length=160, blank=True)
    threads = models.CharField("Threads", max_length=160, blank=True)
    youtube = models.CharField("YouTube канал", max_length=200, blank=True)
    tiktok = models.CharField("TikTok", max_length=160, blank=True)
    facebook = models.CharField("Facebook", max_length=200, blank=True)
    is_verified = models.BooleanField("Проверен", default=False, db_index=True)
    is_vip = models.BooleanField("VIP прогнозист", default=False, db_index=True)
    is_recommended = models.BooleanField(
        "Рекомендовать подписаться",
        default=False,
        db_index=True,
    )
    paid_predictions_enabled = models.BooleanField(
        "Платные прогнозы",
        default=False,
        db_index=True,
    )
    paid_predictions_price = models.DecimalField(
        "Стоимость подписки в месяц",
        max_digits=10,
        decimal_places=2,
        default=0,
    )
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
        if self.paid_predictions_price is None:
            self.paid_predictions_price = 0
        if self.paid_predictions_enabled and self.paid_predictions_price <= 0:
            raise ValidationError(
                {"paid_predictions_price": "Укажите стоимость платной подписки."}
            )

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


class AnalystPaidSubscription(models.Model):
    subscriber = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="paid_prediction_subscriptions",
        verbose_name="Подписчик",
    )
    analyst = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="paid_prediction_subscribers",
        verbose_name="Аналитик",
    )
    price = models.DecimalField("Стоимость на момент подписки", max_digits=10, decimal_places=2)
    starts_at = models.DateTimeField("Начало подписки", default=timezone.now)
    expires_at = models.DateTimeField("Действует до")
    created_at = models.DateTimeField("Создана", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлена", auto_now=True)

    class Meta:
        verbose_name = "Платная подписка на прогнозы"
        verbose_name_plural = "Платные подписки на прогнозы"
        ordering = ("-expires_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("subscriber", "analyst"),
                name="unique_paid_prediction_subscription",
            )
        ]
        indexes = [
            models.Index(fields=("subscriber", "expires_at"), name="paid_sub_subscriber_idx"),
            models.Index(fields=("analyst", "expires_at"), name="paid_sub_analyst_idx"),
        ]

    def clean(self) -> None:
        if self.subscriber_id and self.analyst_id and self.subscriber_id == self.analyst_id:
            raise ValidationError("Нельзя оформить платную подписку на самого себя.")
        if self.analyst_id and self.analyst.role != User.Role.ANALYST:
            raise ValidationError("Платная подписка доступна только на аналитиков.")

    @property
    def is_active(self) -> bool:
        return self.expires_at > timezone.now()

    def __str__(self) -> str:
        return f"{self.subscriber} → {self.analyst} до {self.expires_at:%Y-%m-%d}"


def paid_subscription_expires_at(from_time=None):
    return (from_time or timezone.now()) + timedelta(days=30)


class CapperReferralVisit(models.Model):
    analyst = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="capper_referral_visits",
        verbose_name="Каппер",
    )
    session_key = models.CharField("Сессия", max_length=40)
    visitor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="capper_referral_clicks",
        verbose_name="Пользователь",
        null=True,
        blank=True,
    )
    visits_count = models.PositiveIntegerField("Переходы", default=1)
    first_seen_at = models.DateTimeField("Первый переход", auto_now_add=True)
    last_seen_at = models.DateTimeField("Последний переход", auto_now=True)
    subscribed_at = models.DateTimeField("Подписался", null=True, blank=True)

    class Meta:
        verbose_name = "Переход по реферальной ссылке каппера"
        verbose_name_plural = "Переходы по реферальным ссылкам капперов"
        ordering = ("-last_seen_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("analyst", "session_key"),
                name="unique_capper_referral_session",
            )
        ]
        indexes = [
            models.Index(fields=("analyst", "first_seen_at"), name="capref_analyst_seen_idx"),
            models.Index(fields=("analyst", "subscribed_at"), name="capref_analyst_sub_idx"),
            models.Index(fields=("visitor", "analyst"), name="capref_visitor_analyst_idx"),
        ]

    def clean(self) -> None:
        if self.analyst_id and self.analyst.role != User.Role.ANALYST:
            raise ValidationError("Реферальная ссылка доступна только капперам.")
        if self.visitor_id and self.visitor_id == self.analyst_id:
            raise ValidationError("Переход самого каппера не учитывается как реферальный.")

    def __str__(self) -> str:
        visitor = self.visitor.username if self.visitor_id else self.session_key
        return f"{self.analyst} ← {visitor}"


class MatchPredictionRequest(models.Model):
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="match_prediction_requests",
        verbose_name="Пользователь",
    )
    match = models.ForeignKey(
        "game.Match",
        on_delete=models.CASCADE,
        related_name="prediction_requests",
        verbose_name="Матч",
    )
    created_at = models.DateTimeField("Запрошен", auto_now_add=True)

    class Meta:
        verbose_name = "Запрос прогноза на матч"
        verbose_name_plural = "Запросы прогнозов на матчи"
        ordering = ("-created_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("user", "match"),
                name="unique_match_prediction_request",
            )
        ]
        indexes = [
            models.Index(fields=("match", "created_at"), name="matchreq_match_created_idx"),
            models.Index(fields=("user", "created_at"), name="matchreq_user_created_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.user} → {self.match}"


class CapperMonthlyStat(models.Model):
    """Persisted historical performance snapshot for one capper and calendar month."""

    analyst = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="monthly_capper_stats",
        verbose_name="Каппер",
    )
    month = models.DateField("Месяц", db_index=True)
    bets_count = models.PositiveIntegerField("Прогнозов", default=0)
    wins_count = models.PositiveIntegerField("Выигрышей", default=0)
    losses_count = models.PositiveIntegerField("Проигрышей", default=0)
    refunds_count = models.PositiveIntegerField("Возвратов", default=0)
    total_stake = models.DecimalField("Оборот", max_digits=14, decimal_places=2, default=0)
    total_profit = models.DecimalField("Прибыль", max_digits=14, decimal_places=2, default=0)
    flat_profit_percent = models.DecimalField(
        "Прибыль флэтом, %",
        max_digits=9,
        decimal_places=2,
        default=0,
    )
    roi = models.DecimalField("ROI, %", max_digits=9, decimal_places=2, default=0)
    avg_coefficient = models.DecimalField(
        "Средний коэффициент",
        max_digits=8,
        decimal_places=2,
        default=0,
    )
    hit_rate = models.DecimalField(
        "Проходимость, %",
        max_digits=6,
        decimal_places=2,
        default=0,
    )
    sports_data = models.JSONField(
        "Статистика по видам спорта",
        default=dict,
        blank=True,
    )
    calculated_at = models.DateTimeField("Пересчитано", auto_now=True)

    class Meta:
        verbose_name = "Статистика каппера за месяц"
        verbose_name_plural = "Статистика капперов по месяцам"
        ordering = ("-month", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("analyst", "month"),
                name="unique_capper_monthly_stat",
            )
        ]
        indexes = [
            models.Index(fields=("analyst", "month"), name="capmonth_analyst_month_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.analyst} · {self.month:%Y-%m}"
