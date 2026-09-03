from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone


class CapperBalance(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="capper_balance",
        verbose_name="Пользователь",
    )
    balance = models.DecimalField("Виртуальный баланс", max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлен", auto_now=True)

    class Meta:
        verbose_name = "Виртуальный баланс пользователя"
        verbose_name_plural = "Виртуальные балансы пользователей"
        ordering = ["user_id"]

    def __str__(self) -> str:
        return f"{self.user}: {self.balance}"


class BalanceTransaction(models.Model):
    class Kind(models.TextChoices):
        INITIAL_BONUS = "initial_bonus", "Стартовый баланс"
        VIRTUAL_DEPOSIT = "virtual_deposit", "Виртуальное пополнение"
        REAL_TO_VIRTUAL = "real_to_virtual", "Перевод с реального баланса"
        PREDICTION_STAKE = "prediction_stake", "Списание за прогноз"
        PREDICTION_PAYOUT = "prediction_payout", "Выплата по прогнозу"
        PREDICTION_REFUND = "prediction_refund", "Возврат прогноза"
        COPYBET_STAKE = "copybet_stake", "Списание за копиставку"
        COPYBET_PAYOUT = "copybet_payout", "Выплата по копиставке"
        COPYBET_REFUND = "copybet_refund", "Возврат копиставки"
        ADJUSTMENT = "adjustment", "Корректировка"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="balance_transactions",
        verbose_name="Пользователь",
    )
    kind = models.CharField("Тип", max_length=32, choices=Kind.choices, db_index=True)
    amount = models.DecimalField("Сумма", max_digits=12, decimal_places=2)
    balance_after = models.DecimalField("Баланс после операции", max_digits=12, decimal_places=2)
    related_model = models.CharField("Связанная модель", max_length=100, blank=True)
    related_id = models.PositiveBigIntegerField("Связанный объект", null=True, blank=True)
    note = models.CharField("Комментарий", max_length=255, blank=True)
    created_at = models.DateTimeField("Создана", auto_now_add=True)

    class Meta:
        verbose_name = "Транзакция баланса"
        verbose_name_plural = "Транзакции баланса"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "kind", "related_model", "related_id"],
                condition=Q(related_id__isnull=False),
                name="unique_balance_transaction_subject",
            )
        ]
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["related_model", "related_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()}: {self.amount}"


class CapperRealBalance(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="real_balance",
        verbose_name="Каппер",
    )
    balance = models.DecimalField("Реальный баланс", max_digits=12, decimal_places=2, default=0)
    pending_withdrawal = models.DecimalField("Ожидает вывода", max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлен", auto_now=True)

    class Meta:
        verbose_name = "Реальный баланс каппера"
        verbose_name_plural = "Реальные балансы капперов"
        ordering = ["user_id"]

    def __str__(self) -> str:
        return f"{self.user}: {self.balance}"


class CapperBankStats(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="public_bank_stats",
        verbose_name="Каппер",
    )
    coupons_count = models.PositiveIntegerField("Опубликовано купонов", default=0)
    settled_count = models.PositiveIntegerField("Рассчитано купонов", default=0)
    total_stake = models.DecimalField("Сыграно за всё время", max_digits=14, decimal_places=2, default=0)
    average_stake = models.DecimalField("Средняя ставка", max_digits=14, decimal_places=2, default=0)
    lost_amount = models.DecimalField("Проиграно", max_digits=14, decimal_places=2, default=0)
    earned_amount = models.DecimalField("Заработано", max_digits=14, decimal_places=2, default=0)
    pending_stake = models.DecimalField("Сейчас в игре", max_digits=14, decimal_places=2, default=0)
    net_result = models.DecimalField("Чистый результат", max_digits=14, decimal_places=2, default=0)
    created_at = models.DateTimeField("Создана", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлена", auto_now=True)

    class Meta:
        verbose_name = "Публичный банк каппера"
        verbose_name_plural = "Публичные банки капперов"
        ordering = ["user_id"]

    def __str__(self) -> str:
        return f"{self.user}: {self.net_result}"


class RealBalanceTransaction(models.Model):
    class Kind(models.TextChoices):
        SUBSCRIPTION_INCOME = "subscription_income", "Доход с подписки"
        TOURNAMENT_PRIZE = "tournament_prize", "Приз турнира"
        REAL_DEPOSIT = "real_deposit", "Реальное пополнение"
        VIRTUAL_TOP_UP = "virtual_top_up", "Пополнение виртуального баланса"
        WITHDRAWAL_REQUEST = "withdrawal_request", "Заявка на вывод"
        WITHDRAWAL_CANCEL = "withdrawal_cancel", "Отмена вывода"
        ADJUSTMENT = "adjustment", "Корректировка"

    class Status(models.TextChoices):
        COMPLETED = "completed", "Завершена"
        PENDING = "pending", "Ожидает"
        CANCELED = "canceled", "Отменена"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="real_balance_transactions",
        verbose_name="Каппер",
    )
    kind = models.CharField("Тип", max_length=32, choices=Kind.choices, db_index=True)
    status = models.CharField("Статус", max_length=16, choices=Status.choices, default=Status.COMPLETED, db_index=True)
    amount = models.DecimalField("Сумма", max_digits=12, decimal_places=2)
    balance_after = models.DecimalField("Баланс после операции", max_digits=12, decimal_places=2)
    related_model = models.CharField("Связанная модель", max_length=100, blank=True)
    related_id = models.PositiveBigIntegerField("Связанный объект", null=True, blank=True)
    note = models.CharField("Комментарий", max_length=255, blank=True)
    created_at = models.DateTimeField("Создана", auto_now_add=True)

    class Meta:
        verbose_name = "Транзакция реального баланса"
        verbose_name_plural = "Транзакции реального баланса"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "kind", "related_model", "related_id"],
                condition=Q(related_id__isnull=False),
                name="unique_real_balance_transaction_subject",
            )
        ]
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["related_model", "related_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()}: {self.amount}"


class CopyBettingSubscription(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Активно"
        PAUSED = "paused", "На паузе"
        STOPPED = "stopped", "Остановлено"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="copybetting_subscriptions",
        verbose_name="Пользователь",
    )
    analyst = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="copybetting_followers",
        verbose_name="Каппер",
    )
    status = models.CharField("Статус", max_length=16, choices=Status.choices, default=Status.ACTIVE, db_index=True)
    active_since = models.DateTimeField("Активно с", null=True, blank=True, db_index=True)
    pending_status = models.CharField(
        "Запрошенный статус",
        max_length=16,
        choices=Status.choices,
        default="",
        blank=True,
        db_index=True,
    )
    pending_status_requested_at = models.DateTimeField("Запрошен статус", null=True, blank=True)
    bank_amount = models.DecimalField("Банк для копирования", max_digits=12, decimal_places=2)
    stake_percent = models.DecimalField("Процент от банка на ставку", max_digits=5, decimal_places=2)
    stop_loss_amount = models.DecimalField("Стоп-лосс", max_digits=12, decimal_places=2, default=0)
    max_single_stake = models.DecimalField("Максимум на одну ставку", max_digits=12, decimal_places=2, default=0)
    min_total_coefficient = models.DecimalField("Минимальный общий коэффициент", max_digits=8, decimal_places=2, default=0)
    copy_regular_coupons = models.BooleanField("Копировать обычные прогнозы", default=True)
    copy_tournament_coupons = models.BooleanField("Копировать турнирные прогнозы", default=True)
    allowed_sports = models.ManyToManyField(
        "game.Sport",
        blank=True,
        related_name="copybetting_subscriptions",
        verbose_name="Виды спорта для копирования",
        help_text="Если пусто, копируются все виды спорта.",
    )
    current_loss = models.DecimalField("Текущая просадка", max_digits=12, decimal_places=2, default=0)
    total_staked = models.DecimalField("Сумма ставок", max_digits=12, decimal_places=2, default=0)
    total_profit = models.DecimalField("Чистая прибыль", max_digits=12, decimal_places=2, default=0)
    started_at = models.DateTimeField("Запущено", auto_now_add=True)
    stopped_at = models.DateTimeField("Остановлено", null=True, blank=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        verbose_name = "Настройка копибеттинга"
        verbose_name_plural = "Настройки копибеттинга"
        ordering = ["-started_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["user", "analyst"], name="unique_copybetting_user_analyst"),
            models.CheckConstraint(check=Q(bank_amount__gt=0), name="copybetting_bank_positive"),
            models.CheckConstraint(check=Q(stake_percent__gt=0), name="copybetting_stake_percent_positive"),
            models.CheckConstraint(check=Q(stake_percent__lte=100), name="copybetting_stake_percent_max"),
            models.CheckConstraint(check=Q(stop_loss_amount__gte=0), name="copybetting_stop_loss_non_negative"),
            models.CheckConstraint(check=Q(max_single_stake__gte=0), name="copybetting_max_stake_non_negative"),
            models.CheckConstraint(check=Q(min_total_coefficient__gte=0), name="copybetting_min_coefficient_non_negative"),
        ]
        indexes = [
            models.Index(fields=["analyst", "status", "started_at"]),
            models.Index(fields=["user", "status", "started_at"]),
        ]

    def clean(self) -> None:
        super().clean()
        if self.user_id and self.analyst_id and self.user_id == self.analyst_id:
            raise ValidationError("Нельзя копировать самого себя.")

    def save(self, *args, **kwargs):
        if self.status == self.Status.ACTIVE and not self.active_since:
            self.active_since = timezone.now()
            update_fields = kwargs.get("update_fields")
            if update_fields is not None:
                kwargs["update_fields"] = [*set(update_fields), "active_since"]
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.user} копирует {self.analyst}"


class CopiedBet(models.Model):
    class StateStatus(models.TextChoices):
        PENDING = "pending", "В ожидании"
        WIN = "win", "Выигрыш"
        LOSE = "lose", "Проигрыш"
        REFUND = "refund", "Возврат"

    subscription = models.ForeignKey(
        CopyBettingSubscription,
        on_delete=models.CASCADE,
        related_name="copied_bets",
        verbose_name="Настройка копирования",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="copied_bets",
        verbose_name="Пользователь",
    )
    analyst = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="source_copied_bets",
        verbose_name="Каппер",
    )
    source_coupon = models.ForeignKey(
        "game.PredictionCoupon",
        on_delete=models.CASCADE,
        related_name="copied_bets",
        verbose_name="Исходный прогноз",
    )
    state_status = models.CharField("Результат", max_length=16, choices=StateStatus.choices, default=StateStatus.PENDING, db_index=True)
    stake = models.DecimalField("Сумма", max_digits=12, decimal_places=2)
    possible_payout = models.DecimalField("Возможный выигрыш", max_digits=12, decimal_places=2, default=0)
    profit = models.DecimalField("Прибыль", max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField("Создана", auto_now_add=True)
    settled_at = models.DateTimeField("Рассчитана", null=True, blank=True)

    class Meta:
        verbose_name = "Скопированная ставка"
        verbose_name_plural = "Скопированные ставки"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["user", "source_coupon"], name="unique_user_source_copied_bet"),
            models.CheckConstraint(check=Q(stake__gt=0), name="copied_bet_stake_positive"),
        ]
        indexes = [
            models.Index(fields=["user", "state_status", "created_at"]),
            models.Index(fields=["analyst", "created_at"]),
            models.Index(fields=["source_coupon", "state_status"]),
        ]

    def __str__(self) -> str:
        return f"{self.user}: копия прогноза #{self.source_coupon_id}"
