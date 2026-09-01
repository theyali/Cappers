from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify


def tournament_image_upload_path(instance, filename: str) -> str:
    return f"tournaments/{instance.slug or 'draft'}/{filename}"


def tournament_achievement_icon_upload_path(instance, filename: str) -> str:
    slug = instance.tournament.slug if instance.tournament_id else "draft"
    return f"tournaments/{slug}/achievements/{filename}"


def _unique_slug(model: type[models.Model], value: str, lookup_pk: int | None = None) -> str:
    base_slug = slugify(value, allow_unicode=False)[:255] or "tournament"
    slug = base_slug
    counter = 2
    queryset = model.objects.all()
    if lookup_pk:
        queryset = queryset.exclude(pk=lookup_pk)
    while queryset.filter(slug=slug).exists():
        suffix = f"-{counter}"
        slug = f"{base_slug[:255 - len(suffix)]}{suffix}"
        counter += 1
    return slug


class Tournament(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Черновик"
        PUBLISHED = "published", "Опубликован"
        ARCHIVED = "archived", "Архив"

    class CouponTypeRule(models.TextChoices):
        ANY = "any", "Любой"
        SINGLE = "single", "Только одиночные"
        EXPRESS = "express", "Только экспрессы"

    title = models.CharField("Название турнира", max_length=180)
    slug = models.SlugField("URL", max_length=255, unique=True, blank=True)
    description = models.TextField("Описание", blank=True)
    rules_text = models.TextField("Условия турнира", blank=True)
    status = models.CharField(
        "Статус",
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    starts_at = models.DateTimeField("Дата начала")
    ends_at = models.DateTimeField("Дата окончания")
    card_image = models.ImageField(
        "Изображение карточки",
        upload_to=tournament_image_upload_path,
        blank=True,
        null=True,
    )
    hero_image = models.ImageField(
        "Главное изображение",
        upload_to=tournament_image_upload_path,
        blank=True,
        null=True,
    )
    prize_first = models.DecimalField("Приз за 1 место", max_digits=12, decimal_places=2, default=0)
    prize_second = models.DecimalField("Приз за 2 место", max_digits=12, decimal_places=2, default=0)
    prize_third = models.DecimalField("Приз за 3 место", max_digits=12, decimal_places=2, default=0)
    min_coefficient = models.DecimalField(
        "Минимальный коэффициент",
        max_digits=8,
        decimal_places=2,
        default=Decimal("1.01"),
    )
    min_confidence = models.PositiveSmallIntegerField("Минимальная уверенность, %", default=0)
    coupon_type_rule = models.CharField(
        "Тип прогноза",
        max_length=16,
        choices=CouponTypeRule.choices,
        default=CouponTypeRule.ANY,
    )
    allowed_sports = models.ManyToManyField(
        "game.Sport",
        blank=True,
        related_name="tournaments",
        verbose_name="Разрешённые виды спорта",
        help_text="Если пусто, доступны все виды спорта.",
    )
    is_featured = models.BooleanField("Показывать выше остальных", default=False, db_index=True)
    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлён", auto_now=True)

    class Meta:
        verbose_name = "Турнир"
        verbose_name_plural = "Турниры"
        ordering = ("-is_featured", "-starts_at", "-id")
        indexes = [
            models.Index(fields=("status", "starts_at", "ends_at")),
            models.Index(fields=("is_featured", "starts_at")),
        ]

    def clean(self) -> None:
        super().clean()
        if self.ends_at and self.starts_at and self.ends_at <= self.starts_at:
            raise ValidationError({"ends_at": "Дата окончания должна быть позже даты начала."})
        if self.min_confidence is None or not 0 <= self.min_confidence <= 100:
            raise ValidationError({"min_confidence": "Уверенность должна быть от 0 до 100%."})
        for field in ("prize_first", "prize_second", "prize_third", "min_coefficient"):
            value = getattr(self, field)
            if value is not None and value < 0:
                raise ValidationError({field: "Значение не может быть отрицательным."})

    def save(self, *args, **kwargs) -> None:
        if not self.slug:
            self.slug = _unique_slug(type(self), self.title, self.pk)
        super().save(*args, **kwargs)

    def get_absolute_url(self) -> str:
        return reverse("tournaments:detail", kwargs={"slug": self.slug})

    @property
    def runtime_status(self) -> str:
        now = timezone.now()
        if now < self.starts_at:
            return "upcoming"
        if now > self.ends_at:
            return "finished"
        return "live"

    def __str__(self) -> str:
        return self.title


class TournamentAchievement(models.Model):
    class Kind(models.TextChoices):
        FIRST_PLACE = "first_place", "1 место"
        SECOND_PLACE = "second_place", "2 место"
        THIRD_PLACE = "third_place", "3 место"
        PARTICIPATION = "participation", "Участие"
        CUSTOM = "custom", "Другое"

    tournament = models.ForeignKey(
        Tournament,
        on_delete=models.CASCADE,
        related_name="achievements",
        verbose_name="Турнир",
    )
    title = models.CharField("Название", max_length=140)
    description = models.TextField("Описание", blank=True)
    icon = models.ImageField(
        "Иконка достижения",
        upload_to=tournament_achievement_icon_upload_path,
        blank=True,
        null=True,
    )
    kind = models.CharField("Тип", max_length=24, choices=Kind.choices, default=Kind.CUSTOM)
    sort_order = models.PositiveIntegerField("Порядок", default=0)

    class Meta:
        verbose_name = "Достижение турнира"
        verbose_name_plural = "Достижения турниров"
        ordering = ("tournament", "sort_order", "id")

    def __str__(self) -> str:
        return f"{self.tournament}: {self.title}"


class TournamentParticipant(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", "Участвует"
        LEFT = "left", "Вышел"
        DISQUALIFIED = "disqualified", "Дисквалифицирован"

    tournament = models.ForeignKey(
        Tournament,
        on_delete=models.CASCADE,
        related_name="participants",
        verbose_name="Турнир",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tournament_participations",
        verbose_name="Каппер",
    )
    status = models.CharField(
        "Статус",
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True,
    )
    joined_at = models.DateTimeField("Дата подключения", auto_now_add=True)
    left_at = models.DateTimeField("Дата выхода", null=True, blank=True)

    class Meta:
        verbose_name = "Участник турнира"
        verbose_name_plural = "Участники турниров"
        ordering = ("-joined_at", "-id")
        constraints = [
            models.UniqueConstraint(fields=("tournament", "user"), name="unique_tournament_participant"),
        ]
        indexes = [
            models.Index(fields=("tournament", "status", "joined_at")),
            models.Index(fields=("user", "status", "joined_at")),
        ]

    def clean(self) -> None:
        super().clean()
        if self.user_id and not self.user.is_analyst:
            raise ValidationError({"user": "В турнирах могут участвовать только капперы."})

    def __str__(self) -> str:
        return f"{self.user} · {self.tournament}"


class TournamentCoupon(models.Model):
    tournament = models.ForeignKey(
        Tournament,
        on_delete=models.CASCADE,
        related_name="tournament_coupons",
        verbose_name="Турнир",
    )
    participant = models.ForeignKey(
        TournamentParticipant,
        on_delete=models.CASCADE,
        related_name="tournament_coupons",
        verbose_name="Участник",
    )
    coupon = models.OneToOneField(
        "game.PredictionCoupon",
        on_delete=models.CASCADE,
        related_name="tournament_link",
        verbose_name="Прогноз",
    )
    created_at = models.DateTimeField("Создан", auto_now_add=True)

    class Meta:
        verbose_name = "Прогноз турнира"
        verbose_name_plural = "Прогнозы турниров"
        ordering = ("-created_at", "-id")
        indexes = [
            models.Index(fields=("tournament", "created_at")),
            models.Index(fields=("participant", "created_at")),
        ]

    def clean(self) -> None:
        super().clean()
        if self.participant_id and self.tournament_id and self.participant.tournament_id != self.tournament_id:
            raise ValidationError({"participant": "Участник относится к другому турниру."})
        if self.coupon_id and self.participant_id and self.coupon.author_id != self.participant.user_id:
            raise ValidationError({"coupon": "Автор прогноза должен совпадать с участником турнира."})

    def __str__(self) -> str:
        return f"{self.tournament} · прогноз #{self.coupon_id}"


class TournamentPredictionEntry(models.Model):
    tournament = models.ForeignKey(
        Tournament,
        on_delete=models.CASCADE,
        related_name="prediction_entries",
        verbose_name="Турнир",
    )
    participant = models.ForeignKey(
        TournamentParticipant,
        on_delete=models.CASCADE,
        related_name="prediction_entries",
        verbose_name="Участник",
    )
    tournament_coupon = models.ForeignKey(
        TournamentCoupon,
        on_delete=models.CASCADE,
        related_name="prediction_entries",
        verbose_name="Турнирный прогноз",
    )
    prediction = models.OneToOneField(
        "game.Prediction",
        on_delete=models.CASCADE,
        related_name="tournament_entry",
        verbose_name="Позиция прогноза",
    )
    match = models.ForeignKey(
        "game.Match",
        on_delete=models.PROTECT,
        related_name="tournament_prediction_entries",
        verbose_name="Матч",
    )
    created_at = models.DateTimeField("Создана", auto_now_add=True)

    class Meta:
        verbose_name = "Позиция прогноза турнира"
        verbose_name_plural = "Позиции прогнозов турниров"
        ordering = ("-created_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("tournament", "participant", "match"),
                name="unique_tournament_participant_match",
            ),
        ]
        indexes = [
            models.Index(fields=("tournament", "match")),
            models.Index(fields=("participant", "match")),
        ]

    def clean(self) -> None:
        super().clean()
        if self.participant_id and self.tournament_id and self.participant.tournament_id != self.tournament_id:
            raise ValidationError({"participant": "Участник относится к другому турниру."})
        if self.tournament_coupon_id and self.tournament_coupon.tournament_id != self.tournament_id:
            raise ValidationError({"tournament_coupon": "Прогноз относится к другому турниру."})
        if self.prediction_id and self.tournament_coupon_id and self.prediction.coupon_id != self.tournament_coupon.coupon_id:
            raise ValidationError({"prediction": "Позиция относится к другому прогнозу."})
        if self.prediction_id and self.match_id and self.prediction.match_id != self.match_id:
            raise ValidationError({"match": "Матч должен совпадать с матчем позиции прогноза."})

    def __str__(self) -> str:
        return f"{self.participant} · матч #{self.match_id}"


class TournamentResult(models.Model):
    tournament = models.ForeignKey(
        Tournament,
        on_delete=models.CASCADE,
        related_name="results",
        verbose_name="Турнир",
    )
    participant = models.OneToOneField(
        TournamentParticipant,
        on_delete=models.CASCADE,
        related_name="result",
        verbose_name="Участник",
    )
    rank = models.PositiveIntegerField("Место")
    coupons_count = models.PositiveIntegerField("Прогнозов", default=0)
    wins_count = models.PositiveIntegerField("Выигрышей", default=0)
    losses_count = models.PositiveIntegerField("Проигрышей", default=0)
    refunds_count = models.PositiveIntegerField("Возвратов", default=0)
    pending_count = models.PositiveIntegerField("Ожидают расчёта", default=0)
    total_stake = models.DecimalField("Сумма ставок", max_digits=12, decimal_places=2, default=0)
    profit = models.DecimalField("Прибыль", max_digits=12, decimal_places=2, default=0)
    roi_percent = models.DecimalField("ROI, %", max_digits=8, decimal_places=2, default=0)
    prize_amount = models.DecimalField("Приз", max_digits=12, decimal_places=2, default=0)
    achievement = models.ForeignKey(
        TournamentAchievement,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="results",
        verbose_name="Достижение",
    )
    finalized_at = models.DateTimeField("Зафиксирован", default=timezone.now)

    class Meta:
        verbose_name = "Итог турнира"
        verbose_name_plural = "Итоги турниров"
        ordering = ("tournament", "rank")
        constraints = [
            models.UniqueConstraint(fields=("tournament", "participant"), name="unique_tournament_result_participant"),
            models.UniqueConstraint(fields=("tournament", "rank"), name="unique_tournament_result_rank"),
            models.CheckConstraint(check=Q(rank__gte=1), name="tournament_result_rank_positive"),
        ]

    def __str__(self) -> str:
        return f"{self.tournament} · {self.rank} место"
