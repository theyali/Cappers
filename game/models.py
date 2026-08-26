from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify

from cabinet.models import User


def _unique_slug(model: type[models.Model], value: str, lookup_pk: int | None = None) -> str:
    base_slug = slugify(value, allow_unicode=False)[:255] or "item"
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


class Provider(models.TextChoices):
    NEUROKEFF = "neurokeff", "Neurokeff"


class Country(models.Model):
    provider = models.CharField(max_length=32, choices=Provider.choices, default=Provider.NEUROKEFF)
    external_id = models.PositiveBigIntegerField(null=True, blank=True)
    code = models.CharField(max_length=10, blank=True, db_index=True)
    name = models.CharField(max_length=120, blank=True)
    name_ru = models.CharField(max_length=120, blank=True)
    logo = models.URLField(max_length=500, blank=True)
    raw_data = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Страна"
        verbose_name_plural = "Страны"
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "external_id"],
                name="unique_country_provider_external_id",
            )
        ]
        ordering = ["name_ru", "name", "id"]

    def __str__(self) -> str:
        return self.name_ru or self.name or self.code


class Sport(models.Model):
    provider = models.CharField(max_length=32, choices=Provider.choices, default=Provider.NEUROKEFF)
    external_id = models.PositiveBigIntegerField(null=True, blank=True)
    code = models.CharField(max_length=50, unique=True, db_index=True)
    name = models.CharField(max_length=100)
    name_ru = models.CharField(max_length=100, blank=True)
    image = models.URLField(max_length=500, blank=True)
    raw_data = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Спорт"
        verbose_name_plural = "Виды спорта"
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "external_id"],
                name="unique_sport_provider_external_id",
            )
        ]
        ordering = ["name_ru", "name"]

    def __str__(self) -> str:
        return self.name_ru or self.name


class Venue(models.Model):
    provider = models.CharField(max_length=32, choices=Provider.choices, default=Provider.NEUROKEFF)
    external_id = models.PositiveBigIntegerField(null=True, blank=True)
    name = models.CharField(max_length=150, blank=True)
    name_ru = models.CharField(max_length=150, blank=True)
    city = models.CharField(max_length=150, blank=True)
    city_ru = models.CharField(max_length=150, blank=True)
    capacity = models.PositiveIntegerField(null=True, blank=True)
    logo = models.URLField(max_length=500, blank=True)
    address = models.CharField(max_length=255, blank=True)
    address_ru = models.CharField(max_length=255, blank=True)
    surface = models.CharField(max_length=100, blank=True)
    surface_ru = models.CharField(max_length=100, blank=True)
    raw_data = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Стадион"
        verbose_name_plural = "Стадионы"
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "external_id"],
                name="unique_venue_provider_external_id",
            )
        ]
        ordering = ["name_ru", "name", "id"]

    def __str__(self) -> str:
        return self.name_ru or self.name or f"Venue #{self.external_id or self.pk}"


class League(models.Model):
    provider = models.CharField(max_length=32, choices=Provider.choices, default=Provider.NEUROKEFF)
    external_id = models.PositiveBigIntegerField(db_index=True)
    sport = models.ForeignKey(Sport, related_name="leagues", on_delete=models.CASCADE)
    country = models.ForeignKey(
        Country,
        related_name="leagues",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255)
    name_ru = models.CharField(max_length=255, blank=True)
    logo = models.URLField(max_length=500, blank=True)
    gender = models.CharField(max_length=32, blank=True)
    age_group = models.CharField(max_length=32, blank=True)
    slug = models.SlugField(max_length=255, unique=True, db_index=True, blank=True)
    raw_data = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Лига"
        verbose_name_plural = "Лиги"
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "external_id"],
                name="unique_league_provider_external_id",
            )
        ]
        ordering = ["name_ru", "name"]

    def save(self, *args, **kwargs) -> None:
        if not self.slug:
            self.slug = _unique_slug(self.__class__, f"{self.name}-{self.external_id}", self.pk)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name_ru or self.name


class LeagueSeason(models.Model):
    league = models.ForeignKey(League, related_name="seasons", on_delete=models.CASCADE)
    sport = models.ForeignKey(Sport, related_name="seasons", on_delete=models.CASCADE)
    year = models.PositiveIntegerField(db_index=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_current = models.BooleanField(default=False, db_index=True)
    round_name = models.CharField(max_length=200, blank=True)
    round_name_ru = models.CharField(max_length=200, blank=True)
    round_updated_at = models.DateTimeField(null=True, blank=True)
    raw_data = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Сезон лиги"
        verbose_name_plural = "Сезоны лиг"
        constraints = [
            models.UniqueConstraint(fields=["league", "year"], name="unique_league_season_year"),
        ]
        indexes = [
            models.Index(fields=["league", "is_current"]),
        ]
        ordering = ["-year", "league_id"]

    def __str__(self) -> str:
        return f"{self.league} {self.year}"


class Team(models.Model):
    provider = models.CharField(max_length=32, choices=Provider.choices, default=Provider.NEUROKEFF)
    external_id = models.PositiveBigIntegerField(db_index=True)
    sport = models.ForeignKey(Sport, related_name="teams", on_delete=models.CASCADE)
    country = models.ForeignKey(
        Country,
        related_name="teams",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    venue = models.ForeignKey(
        Venue,
        related_name="teams",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=255)
    name_ru = models.CharField(max_length=255, blank=True)
    logo = models.URLField(max_length=500, blank=True)
    gender = models.CharField(max_length=32, blank=True)
    age_group = models.CharField(max_length=32, blank=True)
    founded = models.PositiveIntegerField(null=True, blank=True)
    slug = models.SlugField(max_length=255, unique=True, db_index=True, blank=True)
    squad = models.JSONField(default=list, blank=True)
    squad_updated_at = models.DateTimeField(null=True, blank=True)
    raw_data = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Команда"
        verbose_name_plural = "Команды"
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "external_id"],
                name="unique_team_provider_external_id",
            )
        ]
        ordering = ["name_ru", "name"]

    def save(self, *args, **kwargs) -> None:
        if not self.slug:
            self.slug = _unique_slug(self.__class__, f"{self.name}-{self.external_id}", self.pk)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name_ru or self.name


class Match(models.Model):
    class SyncScope(models.TextChoices):
        LIVE = "live", "Идет"
        PREMATCH = "prematch", "Скоро"
        FINISHED = "finished", "Завершен"

    provider = models.CharField(
        max_length=32,
        choices=Provider.choices,
        default=Provider.NEUROKEFF,
    )
    sport = models.ForeignKey(
        Sport,
        related_name="matches",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    external_id = models.PositiveBigIntegerField()
    slug = models.SlugField(max_length=320, unique=True, null=True, blank=True, db_index=True)
    sync_scope = models.CharField(max_length=16, choices=SyncScope.choices)
    time_status = models.CharField(max_length=8, blank=True)
    starts_at = models.DateTimeField(null=True, blank=True)

    league = models.ForeignKey(
        League,
        related_name="matches",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    league_season = models.ForeignKey(
        LeagueSeason,
        related_name="matches",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    home_team = models.ForeignKey(
        Team,
        related_name="home_matches",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    away_team = models.ForeignKey(
        Team,
        related_name="away_matches",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    venue = models.ForeignKey(
        Venue,
        related_name="matches",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    score = models.CharField(max_length=32, blank=True)
    live_minute = models.IntegerField(null=True, blank=True)
    live_minute_label = models.CharField(max_length=32, blank=True)

    raw_data = models.JSONField(default=dict, blank=True)
    last_seen_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "external_id"],
                name="unique_football_match_provider_external_id",
            )
        ]
        indexes = [
            models.Index(fields=["sync_scope", "starts_at"]),
            models.Index(fields=["time_status"]),
            models.Index(fields=["sport", "starts_at"]),
            models.Index(fields=["league", "starts_at"]),
        ]
        ordering = ["starts_at", "id"]

    def __str__(self) -> str:
        return f"{self.home_team_name} - {self.away_team_name}"

    def save(self, *args, **kwargs) -> None:
        if not self.slug:
            self.slug = self.build_slug()
        super().save(*args, **kwargs)

    def build_slug(self) -> str:
        title = "-".join(
            [
                self.home_team_name_en or self.home_team_name or "home",
                "vs",
                self.away_team_name_en or self.away_team_name or "away",
                self.league_name_en or self.league_name or "league",
                str(self.external_id),
            ]
        )
        return slugify(title)[:320] or f"match-{self.external_id or self.pk}"

    def get_absolute_url(self) -> str:
        return reverse("game:match_detail", kwargs={"slug": self.slug or self.build_slug()})

    @property
    def sport_code(self) -> str:
        return self.sport.code if self.sport_id and self.sport else "football"

    @property
    def league_name(self) -> str:
        return self.league.name_ru or self.league.name if self.league_id and self.league else self._raw_localized("league", "name", "ru")

    @property
    def league_name_en(self) -> str:
        return self.league.name if self.league_id and self.league else self._raw_localized("league", "name", "en")

    @property
    def league_country(self) -> str:
        if self.league_id and self.league and self.league.country_id and self.league.country:
            return self.league.country.name_ru or self.league.country.name
        return self._raw_localized("league", "country", "name", "ru")

    @property
    def league_country_en(self) -> str:
        if self.league_id and self.league and self.league.country_id and self.league.country:
            return self.league.country.name
        return self._raw_localized("league", "country", "name", "en")

    @property
    def home_team_name(self) -> str:
        return self.home_team.name_ru or self.home_team.name if self.home_team_id and self.home_team else self._raw_localized("teams", "home", "name", "ru")

    @property
    def home_team_name_en(self) -> str:
        return self.home_team.name if self.home_team_id and self.home_team else self._raw_localized("teams", "home", "name", "en")

    @property
    def home_team_logo(self) -> str:
        return self.home_team.logo if self.home_team_id and self.home_team else self._raw_value("teams", "home", "logo")

    @property
    def away_team_name(self) -> str:
        return self.away_team.name_ru or self.away_team.name if self.away_team_id and self.away_team else self._raw_localized("teams", "away", "name", "ru")

    @property
    def away_team_name_en(self) -> str:
        return self.away_team.name if self.away_team_id and self.away_team else self._raw_localized("teams", "away", "name", "en")

    @property
    def away_team_logo(self) -> str:
        return self.away_team.logo if self.away_team_id and self.away_team else self._raw_value("teams", "away", "logo")

    def _raw_value(self, *path: str) -> str:
        value = self.raw_data if isinstance(self.raw_data, dict) else {}
        for key in path:
            if not isinstance(value, dict):
                return ""
            value = value.get(key)
        return str(value or "")

    def _raw_localized(self, *path: str) -> str:
        preferred = path[-1]
        value = self.raw_data if isinstance(self.raw_data, dict) else {}
        for key in path[:-1]:
            if not isinstance(value, dict):
                return ""
            value = value.get(key)
        if isinstance(value, dict):
            fallback = "en" if preferred == "ru" else "ru"
            return str(value.get(preferred) or value.get(fallback) or next(iter(value.values()), "") or "")
        return str(value or "")


class MatchOdds(models.Model):
    match = models.OneToOneField(Match, on_delete=models.CASCADE, related_name="odds")
    home_win_bet = models.FloatField(null=True, blank=True)
    x_bet = models.FloatField(null=True, blank=True)
    away_win_bet = models.FloatField(null=True, blank=True)
    goals_over_2_5 = models.FloatField(null=True, blank=True)
    goals_under_2_5 = models.FloatField(null=True, blank=True)
    fora_1_0 = models.FloatField(null=True, blank=True)
    fora_2_0 = models.FloatField(null=True, blank=True)
    btts_yes = models.FloatField(null=True, blank=True)
    btts_no = models.FloatField(null=True, blank=True)
    d_1x = models.FloatField(null=True, blank=True)
    d_2x = models.FloatField(null=True, blank=True)
    first_time_home_win_bet = models.FloatField(null=True, blank=True)
    first_time_x_bet = models.FloatField(null=True, blank=True)
    first_time_away_win_bet = models.FloatField(null=True, blank=True)
    totals_all = models.JSONField(default=dict, blank=True)
    double_chance_all = models.JSONField(default=dict, blank=True)
    handicaps_all = models.JSONField(default=dict, blank=True)
    btts_all = models.JSONField(default=dict, blank=True)
    team_totals_all = models.JSONField(default=dict, blank=True)
    first_half_totals_all = models.JSONField(default=dict, blank=True)
    first_half_handicaps_all = models.JSONField(default=dict, blank=True)
    half_time_full_time_all = models.JSONField(default=dict, blank=True)
    exact_score_all = models.JSONField(default=dict, blank=True)
    extra_markets = models.JSONField(default=dict, blank=True)
    raw_data = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [models.Index(fields=["home_win_bet", "x_bet", "away_win_bet"])]
        verbose_name = "Коэффициенты"
        verbose_name_plural = "Коэффициенты"

    def __str__(self) -> str:
        return f"Коэффициенты {self.match_id}"


class PredictionCoupon(models.Model):
    class PublishedStatus(models.TextChoices):
        DRAFT = "draft", "Черновик"
        CANCELED = "canceled", "Отменен"
        PUBLISHED = "published", "Опубликован"

    author = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="prediction_coupons",
        verbose_name="Автор",
    )
    published_status = models.CharField(
        "Статус публикации",
        max_length=16,
        choices=PublishedStatus.choices,
        default=PublishedStatus.DRAFT,
        db_index=True,
    )
    total_stake = models.DecimalField("Сумма", max_digits=10, decimal_places=2)
    possible_payout = models.DecimalField("Возможный выигрыш", max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлен", auto_now=True)
    published_at = models.DateTimeField("Опубликован", null=True, blank=True)

    class Meta:
        verbose_name = "Купон прогнозов"
        verbose_name_plural = "Купоны прогнозов"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["author", "published_status", "created_at"]),
        ]

    def clean(self) -> None:
        if self.author_id and self.author.role != User.Role.ANALYST:
            raise ValidationError("Купоны могут создавать только аналитики.")

    def __str__(self) -> str:
        return f"Купон #{self.pk or 'new'}"


class Prediction(models.Model):
    class StateStatus(models.TextChoices):
        WIN = "win", "Выигрыш"
        LOSE = "lose", "Проигрыш"
        REFUND = "refund", "Возврат"

    coupon = models.ForeignKey(
        PredictionCoupon,
        on_delete=models.CASCADE,
        related_name="predictions",
        verbose_name="Купон",
    )
    match = models.ForeignKey(
        Match,
        on_delete=models.PROTECT,
        related_name="predictions",
        verbose_name="Матч",
    )
    market = models.CharField("Рынок", max_length=80)
    selection = models.CharField("Выбор", max_length=120)
    coefficient = models.DecimalField("Коэффициент", max_digits=8, decimal_places=2, default=1)
    stake = models.DecimalField("Сумма", max_digits=10, decimal_places=2)
    comment = models.TextField("Комментарий", max_length=1200)
    state_status = models.CharField(
        "Результат",
        max_length=16,
        choices=StateStatus.choices,
        blank=True,
        db_index=True,
    )
    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлен", auto_now=True)

    class Meta:
        verbose_name = "Прогноз"
        verbose_name_plural = "Прогнозы"
        ordering = ["coupon_id", "id"]
        constraints = [
            models.UniqueConstraint(fields=["coupon", "match"], name="unique_prediction_match_in_coupon"),
        ]
        indexes = [
            models.Index(fields=["match", "state_status"]),
        ]

    def __str__(self) -> str:
        return f"{self.match}: {self.selection}"

    def clean(self) -> None:
        if self.match_id and self.match.sync_scope != Match.SyncScope.PREMATCH:
            raise ValidationError("Прогноз можно создать только на предстоящий матч.")
        if self.stake is not None and self.stake <= 0:
            raise ValidationError("Сумма ставки должна быть больше нуля.")
        if not (self.comment or "").strip():
            raise ValidationError("Комментарий обязателен.")
        if self.coupon_id:
            siblings = self.coupon.predictions.exclude(pk=self.pk)
            if siblings.count() >= 5:
                raise ValidationError("В одном купоне может быть максимум 5 игр.")
