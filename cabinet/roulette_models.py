from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class RouletteSettings(models.Model):
    """Global roulette configuration.

    The project uses a single settings row. User spin state/history is intentionally
    kept out of this model and will be introduced with the spin backend.
    """

    is_enabled = models.BooleanField("Рулетка включена", default=True)
    daily_free_spins = models.PositiveSmallIntegerField(
        "Бесплатных попыток в день",
        default=1,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    reset_hour = models.PositiveSmallIntegerField(
        "Час ежедневного обновления",
        default=0,
        validators=[MinValueValidator(0), MaxValueValidator(23)],
        help_text="Час по часовому поясу проекта, когда становятся доступны ежедневные попытки.",
    )
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        verbose_name = "Настройки рулетки"
        verbose_name_plural = "Настройки рулетки"

    @classmethod
    def load(cls):
        settings, _ = cls.objects.get_or_create(pk=1)
        return settings

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        status = "включена" if self.is_enabled else "выключена"
        return f"Рулетка: {status}, {self.daily_free_spins} попыток/день"


class RoulettePrize(models.Model):
    class RewardType(models.TextChoices):
        VIRTUAL_BALANCE = "virtual_balance", "Виртуальный баланс"
        VIP_DAYS = "vip_days", "VIP на несколько дней"
        FREE_PREDICTIONS = "free_predictions", "Бесплатные прогнозы"
        PROMO_CODE = "promo_code", "Промокод"
        RATING_BOOST = "rating_boost", "Буст рейтинга"
        EXTRA_SPIN = "extra_spin", "Дополнительная попытка"
        NOTHING = "nothing", "Пустой сектор"

    class ConditionLogic(models.TextChoices):
        ALL = "all", "Все условия"
        ANY = "any", "Хотя бы одно условие"

    title = models.CharField("Название", max_length=80)
    short_text = models.CharField("Короткий текст", max_length=140, blank=True)
    icon = models.ImageField(
        "Иконка",
        upload_to="roulette/prizes/%Y/%m/",
        blank=True,
    )
    is_active = models.BooleanField("Активен", default=True, db_index=True)
    sector_order = models.PositiveSmallIntegerField("Порядок сектора", default=0, db_index=True)
    reward_type = models.CharField(
        "Тип награды",
        max_length=32,
        choices=RewardType.choices,
        db_index=True,
    )
    reward_value = models.DecimalField(
        "Величина награды",
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Сумма, количество дней, прогнозов, попыток или размер буста — зависит от типа награды.",
    )
    reward_text = models.CharField(
        "Текстовое значение награды",
        max_length=255,
        blank=True,
        help_text="Например, сам промокод. Не используется для выполнения произвольного кода.",
    )
    weight = models.PositiveIntegerField(
        "Вес выпадения",
        default=1,
        validators=[MinValueValidator(1)],
        help_text="Относительный вес. Чем больше значение, тем чаще сектор может выпадать.",
    )
    active_from = models.DateTimeField("Активен с", null=True, blank=True, db_index=True)
    active_until = models.DateTimeField("Активен до", null=True, blank=True, db_index=True)
    total_award_limit = models.PositiveIntegerField(
        "Общий лимит выдач",
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        help_text="Пусто — без общего лимита.",
    )
    per_user_award_limit = models.PositiveIntegerField(
        "Лимит на пользователя",
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        help_text="Пусто — без лимита на пользователя.",
    )
    daily_award_limit = models.PositiveIntegerField(
        "Дневной лимит выдач",
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
        help_text="Пусто — без дневного лимита.",
    )
    condition_logic = models.CharField(
        "Как применять условия",
        max_length=8,
        choices=ConditionLogic.choices,
        default=ConditionLogic.ALL,
    )
    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлён", auto_now=True)

    class Meta:
        verbose_name = "Приз рулетки"
        verbose_name_plural = "Призы рулетки"
        ordering = ("sector_order", "id")
        indexes = [
            models.Index(fields=("is_active", "sector_order"), name="roulette_prize_active_idx"),
            models.Index(fields=("is_active", "active_from", "active_until"), name="roulette_prize_period_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(reward_value__gte=0),
                name="roulette_prize_value_non_negative",
            ),
            models.CheckConstraint(
                check=models.Q(weight__gt=0),
                name="roulette_prize_weight_positive",
            ),
            models.CheckConstraint(
                check=models.Q(total_award_limit__isnull=True) | models.Q(total_award_limit__gt=0),
                name="roulette_prize_total_limit_positive",
            ),
            models.CheckConstraint(
                check=models.Q(per_user_award_limit__isnull=True) | models.Q(per_user_award_limit__gt=0),
                name="roulette_prize_user_limit_positive",
            ),
            models.CheckConstraint(
                check=models.Q(daily_award_limit__isnull=True) | models.Q(daily_award_limit__gt=0),
                name="roulette_prize_daily_limit_positive",
            ),
            models.CheckConstraint(
                check=(
                    models.Q(active_from__isnull=True)
                    | models.Q(active_until__isnull=True)
                    | models.Q(active_until__gt=models.F("active_from"))
                ),
                name="roulette_prize_valid_period",
            ),
        ]

    def clean(self) -> None:
        super().clean()
        errors = {}

        if self.active_from and self.active_until and self.active_until <= self.active_from:
            errors["active_until"] = "Дата окончания должна быть позже даты начала."

        value = Decimal(str(self.reward_value or 0))
        value_required_types = {
            self.RewardType.VIRTUAL_BALANCE,
            self.RewardType.VIP_DAYS,
            self.RewardType.FREE_PREDICTIONS,
            self.RewardType.RATING_BOOST,
            self.RewardType.EXTRA_SPIN,
        }
        integer_value_types = {
            self.RewardType.VIP_DAYS,
            self.RewardType.FREE_PREDICTIONS,
            self.RewardType.EXTRA_SPIN,
        }

        if self.reward_type in value_required_types and value <= 0:
            errors["reward_value"] = "Для этого типа награды значение должно быть больше нуля."
        if self.reward_type in integer_value_types and value != value.to_integral_value():
            errors["reward_value"] = "Для этого типа награды нужно указать целое количество."
        if self.reward_type == self.RewardType.PROMO_CODE and not self.reward_text.strip():
            errors["reward_text"] = "Для промокода укажите текстовое значение награды."
        if self.reward_type == self.RewardType.NOTHING and value != 0:
            errors["reward_value"] = "Для пустого сектора значение награды должно быть равно нулю."

        if errors:
            raise ValidationError(errors)

    def is_available_at(self, when=None) -> bool:
        when = when or timezone.now()
        if not self.is_active:
            return False
        if self.active_from and when < self.active_from:
            return False
        if self.active_until and when >= self.active_until:
            return False
        return True

    def __str__(self) -> str:
        return self.title


class RoulettePrizeCondition(models.Model):
    class ConditionType(models.TextChoices):
        ALL_USERS = "all_users", "Все пользователи"
        READERS_ONLY = "readers_only", "Только обычные пользователи"
        ANALYSTS_ONLY = "analysts_only", "Только капперы"
        WITHOUT_VIP = "without_vip", "Только без VIP"
        MIN_ACCOUNT_AGE_DAYS = "min_account_age_days", "Минимальный возраст аккаунта"
        MIN_ACTIVITY_COUNT = "min_activity_count", "Минимальная активность"

    NUMERIC_CONDITIONS = {
        ConditionType.MIN_ACCOUNT_AGE_DAYS,
        ConditionType.MIN_ACTIVITY_COUNT,
    }

    prize = models.ForeignKey(
        RoulettePrize,
        on_delete=models.CASCADE,
        related_name="conditions",
        verbose_name="Приз",
    )
    condition_type = models.CharField(
        "Условие",
        max_length=32,
        choices=ConditionType.choices,
    )
    threshold = models.PositiveIntegerField(
        "Порог",
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
        help_text="Используется только для числовых условий: возраст аккаунта или активность.",
    )
    is_active = models.BooleanField("Активно", default=True, db_index=True)
    order = models.PositiveSmallIntegerField("Порядок", default=0)
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        verbose_name = "Условие приза рулетки"
        verbose_name_plural = "Условия призов рулетки"
        ordering = ("order", "id")
        constraints = [
            models.UniqueConstraint(
                fields=("prize", "condition_type"),
                name="unique_roulette_prize_condition_type",
            ),
        ]
        indexes = [
            models.Index(fields=("prize", "is_active", "order"), name="roulette_condition_active_idx"),
        ]

    def clean(self) -> None:
        super().clean()
        if self.condition_type in self.NUMERIC_CONDITIONS and self.threshold is None:
            raise ValidationError({"threshold": "Для этого условия необходимо указать порог."})
        if self.condition_type not in self.NUMERIC_CONDITIONS and self.threshold is not None:
            raise ValidationError({"threshold": "Для этого условия порог не используется."})

    def __str__(self) -> str:
        label = self.get_condition_type_display()
        if self.threshold is None:
            return f"{self.prize}: {label}"
        return f"{self.prize}: {label} ≥ {self.threshold}"
