from django.conf import settings
from django.db import models


class BotAccount(models.Model):
    class Kind(models.TextChoices):
        READER = "reader", "Пользователь"
        EXPERT = "expert", "Эксперт"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="bot_account",
        verbose_name="Пользователь",
    )
    kind = models.CharField("Тип", max_length=16, choices=Kind.choices, db_index=True)
    persona = models.CharField("Персона", max_length=120, blank=True)
    is_active = models.BooleanField("Активен", default=True, db_index=True)
    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлен", auto_now=True)

    class Meta:
        verbose_name = "Бот"
        verbose_name_plural = "Боты"
        ordering = ("kind", "user__username")

    def __str__(self) -> str:
        return f"{self.user.username} · {self.get_kind_display()}"


class BotExpertStrategy(models.Model):
    class RiskProfile(models.TextChoices):
        SAFE = "safe", "Осторожный"
        BALANCED = "balanced", "Баланс"
        AGGRESSIVE = "aggressive", "Агрессивный"

    bot = models.OneToOneField(
        BotAccount,
        on_delete=models.CASCADE,
        related_name="expert_strategy",
        limit_choices_to={"kind": BotAccount.Kind.EXPERT},
        verbose_name="Бот-эксперт",
    )
    cadence_days = models.PositiveSmallIntegerField("Периодичность дней", default=1)
    daily_predictions_min = models.PositiveSmallIntegerField("Минимум прогнозов", default=1)
    daily_predictions_max = models.PositiveSmallIntegerField("Максимум прогнозов", default=2)
    market_preference = models.CharField("Любимый рынок", max_length=40, default="winner")
    risk_profile = models.CharField(
        "Риск",
        max_length=16,
        choices=RiskProfile.choices,
        default=RiskProfile.BALANCED,
    )
    next_run_at = models.DateTimeField("Следующий запуск", null=True, blank=True, db_index=True)
    last_run_at = models.DateTimeField("Последний запуск", null=True, blank=True)

    class Meta:
        verbose_name = "Стратегия бота-эксперта"
        verbose_name_plural = "Стратегии ботов-экспертов"
        ordering = ("next_run_at", "bot__user__username")

    def __str__(self) -> str:
        return f"{self.bot.user.username}: {self.market_preference}/{self.cadence_days}д"


class BotActionLog(models.Model):
    class Action(models.TextChoices):
        FOLLOW = "follow", "Подписка"
        UNFOLLOW = "unfollow", "Отписка"
        LIKE = "like", "Лайк"
        UNLIKE = "unlike", "Снять лайк"
        PREDICTION = "prediction", "Прогноз"

    bot = models.ForeignKey(BotAccount, on_delete=models.CASCADE, related_name="action_logs")
    action = models.CharField("Действие", max_length=24, choices=Action.choices, db_index=True)
    target = models.CharField("Цель", max_length=160, blank=True)
    meta = models.JSONField("Данные", default=dict, blank=True)
    created_at = models.DateTimeField("Создано", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Лог действия бота"
        verbose_name_plural = "Логи действий ботов"
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"{self.bot} · {self.action} · {self.target}"
