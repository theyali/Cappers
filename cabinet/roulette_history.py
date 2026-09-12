import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .roulette_models import RoulettePrize


class RouletteSpin(models.Model):
    class RewardStatus(models.TextChoices):
        PENDING = "pending", "Ожидает выдачи"
        ISSUED = "issued", "Выдано"
        FAILED = "failed", "Ошибка выдачи"
        NOT_REQUIRED = "not_required", "Выдача не требуется"

    operation_id = models.UUIDField(
        "ID операции",
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="roulette_spins",
        verbose_name="Пользователь",
    )
    prize = models.ForeignKey(
        RoulettePrize,
        on_delete=models.SET_NULL,
        related_name="spins",
        verbose_name="Приз",
        null=True,
        blank=True,
    )
    spun_at = models.DateTimeField("Время прокрутки", default=timezone.now, db_index=True)
    attempts_before = models.PositiveIntegerField("Попыток до", default=0)
    attempts_after = models.PositiveIntegerField("Попыток после", default=0)
    next_spin_at = models.DateTimeField(
        "Следующая ежедневная попытка",
        null=True,
        blank=True,
        db_index=True,
    )

    prize_title = models.CharField("Название приза на момент выигрыша", max_length=80)
    prize_short_text = models.CharField(
        "Подпись приза на момент выигрыша",
        max_length=140,
        blank=True,
    )
    prize_icon = models.CharField(
        "Иконка приза на момент выигрыша",
        max_length=500,
        blank=True,
        help_text="Путь к файлу иконки на момент прокрутки.",
    )
    prize_sector_order = models.PositiveSmallIntegerField(
        "Позиция сектора на момент выигрыша",
        default=0,
    )
    reward_type = models.CharField(
        "Тип награды на момент выигрыша",
        max_length=32,
        choices=RoulettePrize.RewardType.choices,
    )
    reward_value = models.DecimalField(
        "Значение награды на момент выигрыша",
        max_digits=12,
        decimal_places=2,
        default=0,
    )
    reward_text = models.CharField(
        "Текст награды на момент выигрыша",
        max_length=255,
        blank=True,
    )

    reward_status = models.CharField(
        "Статус выдачи",
        max_length=16,
        choices=RewardStatus.choices,
        default=RewardStatus.PENDING,
        db_index=True,
    )
    issued_at = models.DateTimeField("Выдано", null=True, blank=True, db_index=True)
    issue_error = models.CharField("Ошибка выдачи", max_length=500, blank=True)
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        verbose_name = "Прокрутка рулетки"
        verbose_name_plural = "История прокруток рулетки"
        ordering = ("-spun_at", "-id")
        indexes = [
            models.Index(fields=("user", "spun_at"), name="roulette_spin_user_time_idx"),
            models.Index(fields=("prize", "spun_at"), name="roulette_spin_prize_time_idx"),
            models.Index(fields=("reward_status", "spun_at"), name="roulette_spin_status_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(attempts_before__gte=0),
                name="roulette_spin_before_nonneg",
            ),
            models.CheckConstraint(
                check=models.Q(attempts_after__gte=0),
                name="roulette_spin_after_nonneg",
            ),
        ]

    @classmethod
    def snapshot_from_prize(cls, prize: RoulettePrize) -> dict:
        return {
            "prize_title": prize.title,
            "prize_short_text": prize.short_text,
            "prize_icon": prize.icon.name if prize.icon else "",
            "prize_sector_order": prize.sector_order,
            "reward_type": prize.reward_type,
            "reward_value": prize.reward_value,
            "reward_text": prize.reward_text,
        }

    @classmethod
    def create_for_spin(
        cls,
        *,
        user,
        prize: RoulettePrize,
        attempts_before: int,
        attempts_after: int,
        next_spin_at=None,
        spun_at=None,
        reward_status=None,
        operation_id=None,
    ):
        if attempts_before < 0 or attempts_after < 0:
            raise ValidationError("Количество попыток не может быть отрицательным.")

        if reward_status is None:
            reward_status = (
                cls.RewardStatus.NOT_REQUIRED
                if prize.reward_type == RoulettePrize.RewardType.NOTHING
                else cls.RewardStatus.PENDING
            )

        create_kwargs = {
            "user": user,
            "prize": prize,
            "spun_at": spun_at or timezone.now(),
            "attempts_before": attempts_before,
            "attempts_after": attempts_after,
            "next_spin_at": next_spin_at,
            "reward_status": reward_status,
            **cls.snapshot_from_prize(prize),
        }
        if operation_id is not None:
            create_kwargs["operation_id"] = operation_id
        return cls.objects.create(**create_kwargs)

    def mark_issued(self, *, issued_at=None) -> None:
        self.reward_status = self.RewardStatus.ISSUED
        self.issued_at = issued_at or timezone.now()
        self.issue_error = ""
        self.save(update_fields=("reward_status", "issued_at", "issue_error", "updated_at"))

    def mark_failed(self, error: str) -> None:
        self.reward_status = self.RewardStatus.FAILED
        self.issued_at = None
        self.issue_error = (error or "")[:500]
        self.save(update_fields=("reward_status", "issued_at", "issue_error", "updated_at"))

    def __str__(self) -> str:
        return f"{self.user} · {self.prize_title} · {self.spun_at:%Y-%m-%d %H:%M}"
