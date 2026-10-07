import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class Payment(models.Model):
    """One purchase paid through an external provider, with the terms it was paid on."""

    class Provider(models.TextChoices):
        CLOUDPAYMENTS = "cloudpayments", "CloudPayments (карта)"
        NOWPAYMENTS = "nowpayments", "NOWPayments (крипто)"

    class Purpose(models.TextChoices):
        COIN_PACKAGE = "coin_package", "Пакет коинов"
        PAID_SUBSCRIPTION = "paid_subscription", "Платная подписка"
        VIP_PLAN = "vip_plan", "VIP-тариф"

    class Status(models.TextChoices):
        CREATED = "created", "Создан"
        PENDING = "pending", "Ожидает оплаты"
        PROCESSING = "processing", "Обрабатывается"
        PARTIALLY_PAID = "partially_paid", "Оплачен частично"
        SUCCEEDED = "succeeded", "Оплачен"
        FAILED = "failed", "Ошибка оплаты"
        CANCELED = "canceled", "Отменён"
        EXPIRED = "expired", "Истёк"
        REFUNDED = "refunded", "Возвращён"

    # The numeric pk links coin and real-money transactions (related_id is an
    # integer); providers and URLs only ever see public_id.
    public_id = models.UUIDField("Публичный ID", unique=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="payments",
        verbose_name="Пользователь",
    )
    provider = models.CharField("Провайдер", max_length=32, choices=Provider.choices, db_index=True)
    purpose = models.CharField("Назначение", max_length=32, choices=Purpose.choices, db_index=True)
    status = models.CharField("Статус", max_length=20, choices=Status.choices, default=Status.CREATED, db_index=True)

    amount = models.DecimalField("Сумма к оплате", max_digits=12, decimal_places=2)
    currency = models.CharField("Валюта", max_length=8, default="RUB")
    amount_rub = models.DecimalField("Цена товара, ₽", max_digits=12, decimal_places=2)
    # Terms of the purchase at checkout: the product is delivered by them even if
    # the package, plan or price changes afterwards.
    product_snapshot = models.JSONField("Снимок товара", default=dict)

    coin_package = models.ForeignKey(
        "wallets.CoinPackage",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="provider_payments",
        verbose_name="Пакет коинов",
    )
    paid_plan = models.ForeignKey(
        "cabinet.AnalystPaidPlan",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="provider_payments",
        verbose_name="Тариф подписки",
    )
    vip_plan = models.ForeignKey(
        "cabinet.VipPlan",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="provider_payments",
        verbose_name="VIP-тариф",
    )

    external_id = models.CharField("ID платежа у провайдера", max_length=64, blank=True)
    external_invoice_id = models.CharField("ID счёта у провайдера", max_length=64, blank=True)
    checkout_url = models.URLField("Ссылка на оплату", max_length=1000, blank=True)
    paid_amount = models.DecimalField("Оплачено", max_digits=24, decimal_places=8, null=True, blank=True)
    paid_currency = models.CharField("Валюта оплаты", max_length=16, blank=True)
    is_test = models.BooleanField("Тестовый платёж", default=False)
    failure_reason = models.CharField("Причина ошибки", max_length=255, blank=True)
    provider_payload = models.JSONField("Последний ответ провайдера", default=dict, blank=True)

    expires_at = models.DateTimeField("Истекает", null=True, blank=True)
    paid_at = models.DateTimeField("Оплачен", null=True, blank=True)
    fulfilled_at = models.DateTimeField("Товар выдан", null=True, blank=True)
    refunded_at = models.DateTimeField("Возвращён", null=True, blank=True)
    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлён", auto_now=True)

    class Meta:
        verbose_name = "Платёж"
        verbose_name_plural = "Платежи"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "external_id"],
                condition=~Q(external_id=""),
                name="unique_payment_provider_external_id",
            ),
            models.CheckConstraint(condition=Q(amount__gt=0), name="payment_amount_positive"),
        ]
        indexes = [
            models.Index(fields=["status", "created_at"], name="payment_status_created_idx"),
            models.Index(fields=["user", "created_at"], name="payment_user_created_idx"),
        ]

    def __str__(self) -> str:
        return f"Платёж {self.public_id} · {self.get_purpose_display()} · {self.get_status_display()}"


class PaymentEvent(models.Model):
    """Every provider notification and status check, as received."""

    provider = models.CharField("Провайдер", max_length=32, db_index=True)
    payment = models.ForeignKey(
        Payment,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="events",
        verbose_name="Платёж",
    )
    event_type = models.CharField("Тип события", max_length=32)
    # Provider-specific key that makes a repeated notification a no-op.
    dedup_key = models.CharField("Ключ идемпотентности", max_length=128)
    external_id = models.CharField("ID у провайдера", max_length=64, blank=True)
    payload = models.JSONField("Данные", default=dict)
    signature_valid = models.BooleanField("Подпись верна", default=False)
    processed_at = models.DateTimeField("Обработано", null=True, blank=True)
    error = models.TextField("Ошибка", blank=True)
    created_at = models.DateTimeField("Получено", auto_now_add=True)

    class Meta:
        verbose_name = "Событие платежа"
        verbose_name_plural = "События платежей"
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["provider", "dedup_key"], name="unique_payment_event_dedup"),
        ]

    def __str__(self) -> str:
        return f"{self.provider}: {self.event_type} · {self.dedup_key}"
