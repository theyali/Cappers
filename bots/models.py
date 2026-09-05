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
        return f"{self.bot.user.username}: {self.risk_profile}/{self.cadence_days}д"


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


class BotPlannedAction(models.Model):
    class Action(models.TextChoices):
        PREDICTION = "prediction", "Прогноз"
        READER_ACTIVITY = "reader_activity", "Лайк/подписка"
        TOURNAMENT_ACTIVITY = "tournament_activity", "Турнир"

    class Status(models.TextChoices):
        PENDING = "pending", "Ожидает"
        RUNNING = "running", "Выполняется"
        DONE = "done", "Выполнено"
        SKIPPED = "skipped", "Пропущено"
        FAILED = "failed", "Ошибка"

    bot = models.ForeignKey(
        BotAccount,
        on_delete=models.CASCADE,
        related_name="planned_actions",
        null=True,
        blank=True,
        verbose_name="Бот",
    )
    action = models.CharField("Действие", max_length=32, choices=Action.choices, db_index=True)
    status = models.CharField(
        "Статус",
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    payload = models.JSONField("Данные", default=dict, blank=True)
    result = models.JSONField("Результат", default=dict, blank=True)
    scheduled_at = models.DateTimeField("Запланировано на", db_index=True)
    started_at = models.DateTimeField("Начато", null=True, blank=True)
    finished_at = models.DateTimeField("Завершено", null=True, blank=True)
    error = models.TextField("Ошибка", blank=True)
    created_at = models.DateTimeField("Создано", auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        verbose_name = "Запланированное действие бота"
        verbose_name_plural = "Запланированные действия ботов"
        ordering = ("scheduled_at", "id")
        indexes = [
            models.Index(fields=("status", "scheduled_at"), name="botplan_status_due_idx"),
            models.Index(fields=("bot", "action", "status"), name="botplan_bot_action_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=("bot", "action"),
                condition=models.Q(status="pending", bot__isnull=False),
                name="unique_pending_bot_action",
            ),
            models.UniqueConstraint(
                fields=("action",),
                condition=models.Q(
                    status="pending",
                    action="tournament_activity",
                    bot__isnull=True,
                ),
                name="unique_pending_tournament_action",
            ),
        ]

    def __str__(self) -> str:
        bot = self.bot.user.username if self.bot_id and self.bot else "system"
        return f"{bot} · {self.action} · {self.status}"


class BotOnlineSession(models.Model):
    bot = models.ForeignKey(
        BotAccount,
        on_delete=models.CASCADE,
        related_name="online_sessions",
        verbose_name="Бот",
    )
    starts_at = models.DateTimeField("Начало", db_index=True)
    ends_at = models.DateTimeField("Конец", db_index=True)
    target_actions = models.PositiveSmallIntegerField("Цель действий", default=0)
    actions_planned = models.PositiveSmallIntegerField("Запланировано действий", default=0)
    actions_done = models.PositiveSmallIntegerField("Выполнено действий", default=0)
    created_at = models.DateTimeField("Создано", auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        verbose_name = "Онлайн-сессия бота"
        verbose_name_plural = "Онлайн-сессии ботов"
        ordering = ("-starts_at", "-id")
        indexes = [
            models.Index(fields=("starts_at", "ends_at"), name="botsession_window_idx"),
            models.Index(fields=("bot", "starts_at"), name="botsession_bot_start_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.bot} · {self.starts_at:%Y-%m-%d %H:%M}"


class BotRuntimeControl(models.Model):
    class Mode(models.TextChoices):
        ALL = "all", "Все включено"
        PAUSED = "paused", "Пауза"
        PRESENCE_ONLY = "presence_only", "Только онлайн"
        TOURNAMENTS_ONLY = "tournaments_only", "Только турниры"

    mode = models.CharField(
        "Режим",
        max_length=24,
        choices=Mode.choices,
        default=Mode.ALL,
    )
    note = models.CharField("Заметка", max_length=255, blank=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        verbose_name = "Управление ботами"
        verbose_name_plural = "Управление ботами"

    def save(self, *args, **kwargs) -> None:
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        control, _ = cls.objects.get_or_create(pk=1)
        return control

    def __str__(self) -> str:
        return self.get_mode_display()
