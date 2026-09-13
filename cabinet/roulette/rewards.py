from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class UserRouletteRewardState(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="roulette_rewards",
        verbose_name="Пользователь",
    )
    vip_until = models.DateTimeField("VIP до", null=True, blank=True, db_index=True)
    free_predictions = models.PositiveIntegerField("Бесплатных прогнозов", default=0)
    rating_boost = models.DecimalField(
        "Буст рейтинга",
        max_digits=12,
        decimal_places=2,
        default=0,
    )
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        verbose_name = "Награды рулетки пользователя"
        verbose_name_plural = "Награды рулетки пользователей"
        ordering = ("user_id",)

    @property
    def has_vip(self) -> bool:
        return bool(self.vip_until and self.vip_until > timezone.now())

    def grant_vip_days(self, days: int, *, now=None, save=True):
        try:
            days = int(days)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Количество VIP-дней должно быть целым числом.") from exc
        if days <= 0:
            raise ValidationError("Количество VIP-дней должно быть больше нуля.")

        now = now or timezone.now()
        starts_at = self.vip_until if self.vip_until and self.vip_until > now else now
        self.vip_until = starts_at + timedelta(days=days)
        if save:
            self.save(update_fields=("vip_until", "updated_at"))
        return self.vip_until

    def grant_free_predictions(self, amount: int, *, save=True) -> int:
        try:
            amount = int(amount)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Количество бесплатных прогнозов должно быть целым числом.") from exc
        if amount <= 0:
            raise ValidationError("Количество бесплатных прогнозов должно быть больше нуля.")

        self.free_predictions += amount
        if save:
            self.save(update_fields=("free_predictions", "updated_at"))
        return self.free_predictions

    def grant_rating_boost(self, amount, *, save=True) -> Decimal:
        amount = Decimal(str(amount or 0))
        if amount <= 0:
            raise ValidationError("Буст рейтинга должен быть больше нуля.")

        self.rating_boost += amount
        if save:
            self.save(update_fields=("rating_boost", "updated_at"))
        return self.rating_boost

    def __str__(self) -> str:
        return f"{self.user}: VIP {self.vip_until or '—'}, free={self.free_predictions}, boost={self.rating_boost}"
