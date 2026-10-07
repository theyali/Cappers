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

    class AccessType(models.TextChoices):
        OPEN = "open", "Открытый"
        CLOSED = "closed", "Закрытый"

    class EntryType(models.TextChoices):
        FREE = "free", "Бесплатный"
        PAID = "paid", "Платный"

    class EligibilityMode(models.TextChoices):
        ALL = "all", "Все условия"
        ANY = "any", "Любое условие"

    title = models.CharField("Название турнира", max_length=180)
    slug = models.SlugField("URL", max_length=255, unique=True, blank=True)
    description = models.TextField("Описание", blank=True)
    rules_text = models.TextField("Условия турнира", blank=True)
    participation_rules_text = models.TextField(
        "Условия участия на странице",
        blank=True,
        default="",
        help_text="Каждая строка показывается отдельным пунктом в блоке «Условия участия».",
    )
    format_rules_text = models.TextField(
        "Формат турнира на странице",
        blank=True,
        default="",
        help_text="Каждая строка показывается отдельным пунктом в блоке «Формат турнира».",
    )
    reward_payout_text = models.CharField(
        "Срок выплаты призов",
        max_length=255,
        blank=True,
        default="",
        help_text="Текст для нижнего блока вкладки «Призы».",
    )
    reward_wallet_text = models.CharField(
        "Куда начисляются деньги",
        max_length=255,
        blank=True,
        default="",
        help_text="Текст для денежного приза во вкладке «Призы».",
    )
    reward_coins_wallet_text = models.CharField(
        "Куда начисляются коины",
        max_length=255,
        blank=True,
        default="",
        help_text="Текст для призовых коинов во вкладке «Призы».",
    )
    reward_rules_text = models.CharField(
        "Условия призовой зоны",
        max_length=255,
        blank=True,
        default="",
        help_text="Текст условий попадания в призовую зону.",
    )
    status = models.CharField(
        "Статус",
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    access_type = models.CharField(
        "Тип доступа",
        max_length=16,
        choices=AccessType.choices,
        default=AccessType.OPEN,
        db_index=True,
    )
    entry_type = models.CharField(
        "Тип участия",
        max_length=16,
        choices=EntryType.choices,
        default=EntryType.FREE,
        db_index=True,
    )
    entry_fee_coins = models.PositiveIntegerField(
        "Стоимость участия, коины",
        default=0,
        help_text="Используется для платных турниров.",
    )
    analysts_only = models.BooleanField(
        "Только капперы",
        default=True,
        help_text="Если включено, участвовать могут только пользователи со статусом каппера.",
    )
    vip_only = models.BooleanField("Только VIP", default=False)
    new_users_only = models.BooleanField("Только новые пользователи", default=False)
    eligibility_mode = models.CharField(
        "Логика условий допуска",
        max_length=16,
        choices=EligibilityMode.choices,
        default=EligibilityMode.ALL,
        help_text="Все активные условия обязательны или достаточно любого одного.",
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
    hero_icon = models.ImageField(
        "Иконка турнира",
        upload_to=tournament_image_upload_path,
        blank=True,
        null=True,
        help_text="Показывается в hero на внутренней странице турнира.",
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
    min_confidence = models.PositiveSmallIntegerField(
        "Минимальная уверенность, %",
        blank=True,
        null=True,
        default=None,
        help_text="Оставьте пустым или укажите 0, если уверенность не участвует в условиях турнира.",
    )
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
    min_user_predictions = models.PositiveIntegerField(
        "Мин. опубликованных прогнозов для участия",
        default=0,
        help_text="0 — не проверять.",
    )
    min_user_wins = models.PositiveIntegerField(
        "Мин. выигранных прогнозов для участия",
        default=0,
        help_text="0 — не проверять.",
    )
    eligibility_sport = models.ForeignKey(
        "game.Sport",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="eligibility_tournaments",
        verbose_name="Спорт для проверки активности",
        help_text="Если выбран, прогнозы и победы для допуска считаются только по этому спорту.",
    )
    is_featured = models.BooleanField("Показывать выше остальных", default=False, db_index=True)
    finalized_at = models.DateTimeField(
        "Итоги зафиксированы",
        null=True,
        blank=True,
        help_text="Итоги фиксируются один раз: таблица замораживается, призы выдаются.",
    )
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
        if self.min_confidence is not None and not 0 <= self.min_confidence <= 100:
            raise ValidationError({"min_confidence": "Уверенность должна быть от 0 до 100%."})
        for field in ("prize_first", "prize_second", "prize_third", "min_coefficient"):
            value = getattr(self, field)
            if value is not None and value < 0:
                raise ValidationError({field: "Значение не может быть отрицательным."})
        if self.entry_type == self.EntryType.PAID and self.entry_fee_coins <= 0:
            raise ValidationError({"entry_fee_coins": "Для платного турнира укажите стоимость участия."})

    def save(self, *args, **kwargs) -> None:
        if not self.slug:
            self.slug = _unique_slug(type(self), self.title, self.pk)
        super().save(*args, **kwargs)

    def get_absolute_url(self) -> str:
        return reverse("tournaments:detail", kwargs={"slug": self.slug})

    def has_money_prizes(self) -> bool:
        if any(value > 0 for value in (self.prize_first, self.prize_second, self.prize_third)):
            return True
        return self.prizes.filter(is_active=True, money_amount__gt=0).exists()

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


class TournamentFAQ(models.Model):
    question = models.CharField("Вопрос", max_length=220)
    answer = models.TextField("Ответ")
    sort_order = models.PositiveIntegerField("Порядок", default=0)
    is_active = models.BooleanField("Активен", default=True)
    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлён", auto_now=True)

    class Meta:
        verbose_name = "FAQ турниров"
        verbose_name_plural = "FAQ турниров"
        ordering = ("sort_order", "id")
        indexes = [
            models.Index(fields=("is_active", "sort_order")),
        ]

    def __str__(self) -> str:
        return self.question


class TournamentPrize(models.Model):
    tournament = models.ForeignKey(
        Tournament,
        on_delete=models.CASCADE,
        related_name="prizes",
        verbose_name="Турнир",
    )
    place = models.PositiveIntegerField("Место")
    money_amount = models.DecimalField(
        "Денежный приз",
        max_digits=12,
        decimal_places=2,
        default=0,
    )
    coins_amount = models.PositiveIntegerField(
        "Коины",
        default=0,
        help_text="Дополнительные коины на виртуальный счет.",
    )
    vip_days = models.PositiveIntegerField(
        "VIP, дней",
        default=0,
        help_text="Сколько дней VIP выдать вместе с призом.",
    )
    achievement = models.ForeignKey(
        TournamentAchievement,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="prizes",
        verbose_name="Достижение",
    )
    title = models.CharField(
        "Название награды",
        max_length=140,
        blank=True,
        help_text="Например: VIP на 3 месяца, бонус коинов, специальный статус.",
    )
    description = models.TextField("Описание награды", blank=True)
    sort_order = models.PositiveIntegerField("Порядок", default=0)
    is_active = models.BooleanField("Активен", default=True)
    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлён", auto_now=True)

    class Meta:
        verbose_name = "Приз турнира"
        verbose_name_plural = "Призы турниров"
        ordering = ("tournament", "place", "sort_order", "id")
        constraints = [
            models.UniqueConstraint(fields=("tournament", "place"), name="unique_tournament_prize_place"),
        ]
        indexes = [
            models.Index(fields=("tournament", "is_active", "sort_order", "place")),
        ]

    def clean(self) -> None:
        super().clean()
        if self.money_amount is not None and self.money_amount < 0:
            raise ValidationError({"money_amount": "Значение не может быть отрицательным."})
        if self.achievement_id and self.tournament_id and self.achievement.tournament_id != self.tournament_id:
            raise ValidationError({"achievement": "Достижение должно относиться к этому же турниру."})

    def __str__(self) -> str:
        return f"{self.tournament}: {self.place} место"


class TournamentPrizeAward(models.Model):
    tournament = models.ForeignKey(
        Tournament,
        on_delete=models.CASCADE,
        related_name="prize_awards",
        verbose_name="Турнир",
    )
    participant = models.ForeignKey(
        "TournamentParticipant",
        on_delete=models.CASCADE,
        related_name="prize_awards",
        verbose_name="Участник",
    )
    prize = models.ForeignKey(
        TournamentPrize,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="awards",
        verbose_name="Приз",
    )
    money_awarded = models.DecimalField("Выдано денег", max_digits=12, decimal_places=2, default=0)
    coins_awarded = models.PositiveIntegerField("Выдано коинов", default=0)
    vip_days_awarded = models.PositiveIntegerField("Выдано VIP-дней", default=0)
    achievement_awarded = models.ForeignKey(
        TournamentAchievement,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="prize_awards",
        verbose_name="Выданное достижение",
    )
    created_at = models.DateTimeField("Выдано", auto_now_add=True)

    class Meta:
        verbose_name = "Выдача приза турнира"
        verbose_name_plural = "Выдачи призов турниров"
        ordering = ("-created_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("tournament", "participant"),
                name="unique_tournament_prize_award_participant",
            ),
        ]
        indexes = [
            models.Index(fields=("tournament", "created_at")),
            models.Index(fields=("participant", "created_at")),
        ]

    def clean(self) -> None:
        super().clean()
        if self.participant_id and self.tournament_id and self.participant.tournament_id != self.tournament_id:
            raise ValidationError({"participant": "Участник относится к другому турниру."})
        if self.prize_id and self.tournament_id and self.prize.tournament_id != self.tournament_id:
            raise ValidationError({"prize": "Приз относится к другому турниру."})
        if (
            self.achievement_awarded_id
            and self.tournament_id
            and self.achievement_awarded.tournament_id != self.tournament_id
        ):
            raise ValidationError({"achievement_awarded": "Достижение относится к другому турниру."})

    def __str__(self) -> str:
        return f"{self.tournament}: {self.participant} · приз"


class TournamentEligibilityRule(models.Model):
    class RuleType(models.TextChoices):
        VIP_STATUS = "vip_status", "VIP-статус"
        NEW_USER = "new_user", "Новый пользователь"
        TOURNAMENT_WINS = "tournament_wins", "Победы в турнирах"
        PREDICTIONS_COUNT = "predictions_count", "Опубликованные прогнозы"
        WINNING_PREDICTIONS_COUNT = "winning_predictions_count", "Выигранные прогнозы"
        FOLLOWERS_COUNT = "followers_count", "Подписчики"
        LIKES_COUNT = "likes_count", "Лайки"
        LIVE_PREDICTIONS_COUNT = "live_predictions_count", "Live-прогнозы"
        CUSTOM_METRIC = "custom_metric", "Другая метрика"

    class Operator(models.TextChoices):
        GTE = "gte", "Больше или равно"
        LTE = "lte", "Меньше или равно"
        EQ = "eq", "Равно"

    tournament = models.ForeignKey(
        Tournament,
        on_delete=models.CASCADE,
        related_name="eligibility_rules",
        verbose_name="Турнир",
    )
    rule_type = models.CharField("Тип условия", max_length=40, choices=RuleType.choices)
    operator = models.CharField("Оператор", max_length=8, choices=Operator.choices, default=Operator.GTE)
    value = models.PositiveIntegerField("Значение", default=1)
    sport = models.ForeignKey(
        "game.Sport",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="tournament_eligibility_rules",
        verbose_name="Спорт",
        help_text="Если выбран, условие считается только по этому виду спорта.",
    )
    title = models.CharField("Название условия", max_length=160, blank=True)
    description = models.TextField("Описание", blank=True)
    sort_order = models.PositiveIntegerField("Порядок", default=0)
    is_active = models.BooleanField("Активно", default=True)
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        verbose_name = "Условие допуска к турниру"
        verbose_name_plural = "Условия допуска к турнирам"
        ordering = ("tournament", "sort_order", "id")
        indexes = [
            models.Index(fields=("tournament", "is_active", "sort_order")),
            models.Index(fields=("rule_type", "is_active")),
        ]

    def __str__(self) -> str:
        title = self.title or self.get_rule_type_display()
        return f"{self.tournament}: {title}"


class TournamentStage(models.Model):
    tournament = models.ForeignKey(
        Tournament,
        on_delete=models.CASCADE,
        related_name="stages",
        verbose_name="Турнир",
    )
    title = models.CharField("Название", max_length=120)
    period = models.CharField("Период", max_length=120, blank=True)
    description = models.TextField("Описание", blank=True)
    sort_order = models.PositiveIntegerField("Порядок", default=0)
    is_active = models.BooleanField("Активен", default=True)

    class Meta:
        verbose_name = "Этап турнира"
        verbose_name_plural = "Этапы турниров"
        ordering = ("tournament", "sort_order", "id")
        indexes = [
            models.Index(fields=("tournament", "is_active", "sort_order")),
        ]

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
