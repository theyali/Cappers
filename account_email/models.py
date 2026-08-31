from django.conf import settings
from django.db import models
from django.utils import timezone


class EmailChangeRequest(models.Model):
    class Purpose(models.TextChoices):
        ADD = "add", "Добавление почты"
        CHANGE = "change", "Смена почты"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="email_change_requests",
        verbose_name="Пользователь",
    )
    purpose = models.CharField("Сценарий", max_length=16, choices=Purpose.choices)
    current_email = models.EmailField("Текущая почта", blank=True)
    new_email = models.EmailField("Новая почта", blank=True)
    current_token = models.CharField(
        "Токен подтверждения текущей почты",
        max_length=96,
        unique=True,
        null=True,
        blank=True,
    )
    code_hash = models.CharField("Хеш кода новой почты", max_length=128, blank=True)
    current_confirmed_at = models.DateTimeField("Текущая почта подтверждена", null=True, blank=True)
    new_code_sent_at = models.DateTimeField("Код на новую почту отправлен", null=True, blank=True)
    completed_at = models.DateTimeField("Завершено", null=True, blank=True)
    expires_at = models.DateTimeField("Истекает")
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        verbose_name = "Запрос смены почты"
        verbose_name_plural = "Запросы смены почты"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("user", "completed_at", "expires_at"), name="email_req_user_state_idx"),
            models.Index(fields=("new_email",), name="email_req_new_email_idx"),
        ]

    @property
    def is_expired(self) -> bool:
        return self.expires_at <= timezone.now()

    def __str__(self) -> str:
        return f"{self.user_id}: {self.get_purpose_display()} -> {self.new_email or 'pending'}"


class PasswordResetRequest(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="password_reset_requests",
        verbose_name="Пользователь",
    )
    token_hash = models.CharField("Хеш токена", max_length=128)
    password_fingerprint = models.CharField("Отпечаток пароля", max_length=64)
    opened_at = models.DateTimeField("Ссылка открыта", null=True, blank=True)
    revoked_at = models.DateTimeField("Отозвано", null=True, blank=True)
    completed_at = models.DateTimeField("Пароль изменён", null=True, blank=True)
    expires_at = models.DateTimeField("Истекает")
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        verbose_name = "Запрос сброса пароля"
        verbose_name_plural = "Запросы сброса пароля"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(
                fields=("user", "opened_at", "revoked_at", "completed_at"),
                name="pwd_reset_user_state_idx",
            ),
            models.Index(fields=("expires_at",), name="pwd_reset_expires_idx"),
        ]

    @property
    def is_expired(self) -> bool:
        return self.expires_at <= timezone.now()

    @property
    def link_is_active(self) -> bool:
        return (
            self.opened_at is None
            and self.revoked_at is None
            and self.completed_at is None
            and not self.is_expired
        )

    def __str__(self) -> str:
        return f"Сброс пароля #{self.pk} для {self.user_id}"
