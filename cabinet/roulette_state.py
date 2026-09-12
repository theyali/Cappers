from datetime import datetime, time, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .roulette_models import RouletteSettings


def roulette_daily_window(roulette_settings: RouletteSettings, now=None):
    """Return the current daily grant window start and the next reset time."""
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

    @classmethod
    def for_user(cls, user, *, now=None, refresh=True):
        state, _ = cls.objects.get_or_create(user=user)
        if refresh:
            state.refresh_daily_spins(now=now)
        return state

    def refresh_daily_spins(self, *, now=None, roulette_settings=None, save=True) -> int:
        """Grant the configured daily spins once per reset window.

        Missed days are not accumulated. If the user does not open the roulette for
        several days, the next request grants only the current day's allowance.
        Existing bonus/extra spins are preserved because the daily allowance is added
        to the current balance instead of replacing it.
        """
        now = now or timezone.now()
        roulette_settings = roulette_settings or RouletteSettings.load()

        if not roulette_settings.is_enabled:
            if self.next_spin_at is not None:
                self.next_spin_at = None
                if save:
                    self.save(update_fields=("next_spin_at", "updated_at"))
            return 0

        window_start, next_reset = roulette_daily_window(roulette_settings, now)
        granted = 0
        changed = False

        already_granted = (
            self.last_daily_grant_at is not None
            and self.last_daily_grant_at >= window_start
        )

        if roulette_settings.daily_free_spins > 0 and not already_granted:
            granted = int(roulette_settings.daily_free_spins)
            self.available_spins += granted
            self.last_daily_grant_at = window_start
            changed = True

        if self.next_spin_at != next_reset:
            self.next_spin_at = next_reset
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
