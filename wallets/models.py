from django.conf import settings
from django.db import models
from django.db.models import Q


class CapperBalance(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="capper_balance",
        verbose_name="Каппер",
    )
    balance = models.DecimalField("Баланс", max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлен", auto_now=True)

    class Meta:
        verbose_name = "Баланс каппера"
        verbose_name_plural = "Балансы капперов"
        ordering = ["user_id"]

    def __str__(self) -> str:
        return f"{self.user}: {self.balance}"


class BalanceTransaction(models.Model):
    class Kind(models.TextChoices):
        INITIAL_BONUS = "initial_bonus", "Стартовый баланс"
        VIRTUAL_DEPOSIT = "virtual_deposit", "Виртуальное пополнение"
        PREDICTION_STAKE = "prediction_stake", "Списание за прогноз"
        PREDICTION_PAYOUT = "prediction_payout", "Выплата по прогнозу"
        PREDICTION_REFUND = "prediction_refund", "Возврат прогноза"
        ADJUSTMENT = "adjustment", "Корректировка"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="balance_transactions",
        verbose_name="Каппер",
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
