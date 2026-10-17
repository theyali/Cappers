from datetime import datetime, time, timedelta, timezone as datetime_timezone

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .models import RouletteSettings


FREE_SPIN_INTERVAL = timedelta(hours=24)


def roulette_daily_window(roulette_settings: RouletteSettings, now=None):
    """Return the calendar window for prize award limits, not free spin grants."""
    now = now or timezone.now()
    local_now = timezone.localtime(now)
    current_tz = local_now.tzinfo

    reset_today = timezone.make_aware(
        datetime.combine(local_now.date(), time(hour=roulette_settings.reset_hour)),
        timezone=current_tz,
    )

    if local_now >= reset_today:
        window_start = reset_today
        next_date = local_now.date() + timedelta(days=1)
        next_reset = timezone.make_aware(
            datetime.combine(next_date, time(hour=roulette_settings.reset_hour)),
            timezone=current_tz,
        )
    else:
        previous_date = local_now.date() - timedelta(days=1)
        window_start = timezone.make_aware(
            datetime.combine(previous_date, time(hour=roulette_settings.reset_hour)),
            timezone=current_tz,
        )
        next_reset = reset_today

    return window_start, next_reset


class UserRouletteState(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="roulette_state",
        verbose_name="Пользователь",
    )
    available_spins = models.PositiveIntegerField("Доступно попыток", default=0)
    next_spin_at = models.DateTimeField(
        "Следующая ежедневная попытка",
        null=True,
        blank=True,
        db_index=True,
    )
    last_spin_at = models.DateTimeField(
        "Последняя прокрутка",
        null=True,
        blank=True,
        db_index=True,
    )
    total_spins = models.PositiveBigIntegerField("Всего прокруток", default=0)
    last_daily_grant_at = models.DateTimeField(
        "Последнее ежедневное начисление",
        null=True,
        blank=True,
        db_index=True,
    )
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        verbose_name = "Состояние рулетки пользователя"
        verbose_name_plural = "Состояния рулетки пользователей"
        ordering = ("user_id",)
        indexes = [
            models.Index(
                fields=("available_spins", "next_spin_at"),
                name="roulette_state_ready_idx",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(available_spins__gte=0),
                name="roulette_state_available_spins_nonneg",
            ),
        ]

    @classmethod
    def for_user(cls, user, *, now=None, refresh=True):
        state, _ = cls.objects.get_or_create(user=user)
        if refresh:
            state.refresh_daily_spins(now=now)
        return state

    def refresh_daily_spins(self, *, now=None, roulette_settings=None, save=True) -> int:
        """Refill free spins no sooner than 24 hours after the last spin.

        An untouched allowance does not refill again or start a cooldown on reads.
        Extra spins remain spendable during the cooldown and are never removed.
        Every successful spin restarts the refill clock, including an extra spin.
        """
        now = now or timezone.now()
        roulette_settings = roulette_settings or RouletteSettings.load()

        if not roulette_settings.is_enabled or roulette_settings.daily_free_spins <= 0:
            if self.next_spin_at is not None:
                self.next_spin_at = None
                if save:
                    self.save(update_fields=("next_spin_at", "updated_at"))
            return 0

        next_refill = (
            self.last_spin_at.astimezone(datetime_timezone.utc) + FREE_SPIN_INTERVAL
            if self.last_spin_at else None
        )
        granted = 0
        changed = False

        already_granted = (
            self.available_spins > 0
            and self.last_daily_grant_at is not None
            and (self.last_spin_at is None or self.last_daily_grant_at > self.last_spin_at)
        )

        if not already_granted and (next_refill is None or now >= next_refill):
            granted = int(roulette_settings.daily_free_spins)
            self.available_spins += granted
            self.last_daily_grant_at = now
            already_granted = True
            changed = True

        next_spin_at = None if already_granted else next_refill
        if self.next_spin_at != next_spin_at:
            self.next_spin_at = next_spin_at
            changed = True

        if changed and save:
            self.save(
                update_fields=(
                    "available_spins",
                    "last_daily_grant_at",
                    "next_spin_at",
                    "updated_at",
                )
            )

        return granted

    def grant_spins(self, amount: int, *, save=True) -> int:
        """Add non-daily spins, for example from a promo, referral or prize."""
        try:
            amount = int(amount)
        except (TypeError, ValueError) as exc:
            raise ValidationError("Количество попыток должно быть целым числом.") from exc

        if amount <= 0:
            raise ValidationError("Количество дополнительных попыток должно быть больше нуля.")

        self.available_spins += amount
        if save:
            self.save(update_fields=("available_spins", "updated_at"))
        return self.available_spins

    def consume_spin(self, *, now=None, roulette_settings=None, save=True) -> int:
        """Consume one spin and update counters.

        The actual prize selection endpoint must call this under transaction.atomic()
        with select_for_update() so two simultaneous requests cannot spend one spin.
        """
        now = now or timezone.now()
        roulette_settings = roulette_settings or RouletteSettings.load()

        if not roulette_settings.is_enabled:
            raise ValidationError("Рулетка временно отключена.")

        self.refresh_daily_spins(
            now=now,
            roulette_settings=roulette_settings,
            save=False,
        )

        if self.available_spins <= 0:
            raise ValidationError("Нет доступных попыток.")

        self.available_spins -= 1
        self.total_spins += 1
        self.last_spin_at = now
        self.next_spin_at = (
            now.astimezone(datetime_timezone.utc) + FREE_SPIN_INTERVAL
            if roulette_settings.daily_free_spins > 0 else None
        )

        if save:
            self.save(
                update_fields=(
                    "available_spins",
                    "next_spin_at",
                    "last_spin_at",
                    "total_spins",
                    "last_daily_grant_at",
                    "updated_at",
                )
            )

        return self.available_spins

    def __str__(self) -> str:
        return f"{self.user}: {self.available_spins} попыток"
