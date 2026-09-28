from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.urls import reverse
from tinymce.models import HTMLField

from game.models import PredictionCoupon


SELF_REACTION_ERROR = "Нельзя лайкать или сохранять собственный прогноз."


def _validate_not_own_prediction_reaction(*, prediction_id, user_id):
    if not prediction_id or not user_id:
        return
    if PredictionCoupon.objects.filter(pk=prediction_id, author_id=user_id).exists():
        raise ValidationError(SELF_REACTION_ERROR)


class ArticleCategory(models.Model):
    name = models.CharField("Название", max_length=120, unique=True)
    slug = models.SlugField("Slug", max_length=140, unique=True)
    is_active = models.BooleanField("Активна", default=True, db_index=True)
    sort_order = models.PositiveSmallIntegerField("Порядок", default=100, db_index=True)
    created_at = models.DateTimeField("Создана", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлена", auto_now=True)

    class Meta:
        verbose_name = "Категория статьи"
        verbose_name_plural = "Категории статей"
        ordering = ("sort_order", "name", "id")

    def __str__(self) -> str:
        return self.name


class NewsCategory(models.Model):
    name = models.CharField("Название", max_length=120, unique=True)
    slug = models.SlugField("Slug", max_length=140, unique=True)
    is_active = models.BooleanField("Активна", default=True, db_index=True)
    sort_order = models.PositiveSmallIntegerField("Порядок", default=100, db_index=True)
    created_at = models.DateTimeField("Создана", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлена", auto_now=True)

    class Meta:
        verbose_name = "Категория новости"
        verbose_name_plural = "Категории новостей"
        ordering = ("sort_order", "name", "id")

    def __str__(self) -> str:
        return self.name


class ExpertRankingSnapshot(models.Model):
    """Materialized capper ranking variant used by public pages."""

    period = models.CharField("Период", max_length=16, db_index=True)
    sport_code = models.CharField("Вид спорта", max_length=50, default="all", db_index=True)
    group = models.CharField("Группа", max_length=16, default="all", db_index=True)
    roi_period_days = models.PositiveIntegerField(
        "Период ROI, дней",
        null=True,
        blank=True,
        db_index=True,
    )
    entries_count = models.PositiveIntegerField("Записей", default=0)
    built_at = models.DateTimeField("Собран", auto_now=True)

    class Meta:
        verbose_name = "Снимок рейтинга экспертов"
        verbose_name_plural = "Снимки рейтинга экспертов"
        constraints = [
            models.UniqueConstraint(
                fields=("period", "sport_code", "group", "roi_period_days"),
                name="uniq_exp_rank_snapshot",
                nulls_distinct=False,
            )
        ]
        indexes = [
            models.Index(
                fields=("period", "sport_code", "group", "roi_period_days"),
                name="exp_rank_snap_lookup_idx",
            ),
        ]

    def __str__(self) -> str:
        roi = self.roi_period_days if self.roi_period_days is not None else "all"
        return f"{self.period} · {self.sport_code} · {self.group} · roi={roi}"


class ExpertRankingEntry(models.Model):
    snapshot = models.ForeignKey(
        ExpertRankingSnapshot,
        on_delete=models.CASCADE,
        related_name="entries",
        verbose_name="Снимок",
    )
    analyst = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="expert_ranking_entries",
        verbose_name="Аналитик",
    )
    rank = models.PositiveIntegerField("Место", db_index=True)
    metrics = models.JSONField("Метрики", default=dict, blank=True)
    ranking_reason = models.CharField("Причина рейтинга", max_length=255, blank=True)
    trust_index = models.DecimalField("Индекс доверия", max_digits=6, decimal_places=2, default=0)
    ranking_score = models.DecimalField("Рейтинговый балл", max_digits=14, decimal_places=4, default=0)
    author_roi = models.DecimalField("ROI отображения", max_digits=9, decimal_places=2, default=0)
    author_roi_all_time = models.DecimalField("ROI за всё время", max_digits=9, decimal_places=2, default=0)
    settled_count = models.PositiveIntegerField("Рассчитанных прогнозов", default=0)
    roi_settled_count = models.PositiveIntegerField("Рассчитанных прогнозов ROI", default=0)
    followers_count = models.PositiveIntegerField("Подписчиков", default=0)
    publications_count = models.PositiveIntegerField("Публикаций", default=0)
    wins_count = models.PositiveIntegerField("Выигрышей", default=0)
    losses_count = models.PositiveIntegerField("Проигрышей", default=0)
    sports_count = models.PositiveIntegerField("Видов спорта", default=0)
    recent_publications_count = models.PositiveIntegerField("Публикаций за 30 дней", default=0)
    last_publication_at = models.DateTimeField("Последняя публикация", null=True, blank=True)
    is_vip_active = models.BooleanField("VIP активен", default=False)
    vip_ends_at = models.DateTimeField("VIP до", null=True, blank=True)
    vip_subscription_activated_at = models.DateTimeField("VIP активирован", null=True, blank=True)
    created_at = models.DateTimeField("Создан", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлён", auto_now=True)

    class Meta:
        verbose_name = "Запись рейтинга экспертов"
        verbose_name_plural = "Записи рейтинга экспертов"
        ordering = ("snapshot", "rank")
        constraints = [
            models.UniqueConstraint(
                fields=("snapshot", "analyst"),
                name="uniq_exp_rank_entry_analyst",
            ),
            models.UniqueConstraint(
                fields=("snapshot", "rank"),
                name="uniq_exp_rank_entry_rank",
            ),
        ]
        indexes = [
            models.Index(fields=("snapshot", "rank"), name="expert_rank_entry_rank_idx"),
            models.Index(fields=("analyst",), name="expert_rank_entry_analyst_idx"),
        ]

    def __str__(self) -> str:
        return f"#{self.rank} · {self.analyst_id} · {self.snapshot}"


class Article(models.Model):
    title = models.CharField("Заголовок", max_length=220)
    slug = models.SlugField("Slug", max_length=240, unique=True)
    category = models.ForeignKey(
        ArticleCategory,
        on_delete=models.SET_NULL,
        related_name="articles",
        verbose_name="Категория",
        blank=True,
        null=True,
    )
    description = models.TextField("Краткое описание", max_length=700)
    image = models.ImageField("Изображение", upload_to="articles/%Y/%m/", blank=True, null=True)
    reading_time_minutes = models.PositiveSmallIntegerField("Время чтения, мин", default=5)
    tags = models.CharField("Теги", max_length=300, blank=True, help_text="Через запятую")
    is_main = models.BooleanField("Главная статья", default=False, db_index=True)
    content = HTMLField("Контент")
    is_published = models.BooleanField("Опубликована", default=True, db_index=True)
    created_at = models.DateTimeField("Создана", auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField("Обновлена", auto_now=True)

    class Meta:
        verbose_name = "Статья"
        verbose_name_plural = "Статьи"
        ordering = ("-created_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("is_main",),
                condition=models.Q(is_main=True),
                name="unique_main_article",
            )
        ]

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.is_main:
                type(self).objects.filter(is_main=True).exclude(pk=self.pk).update(is_main=False)
            return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.title

    @property
    def tag_list(self) -> list[str]:
        return [tag.strip() for tag in self.tags.split(",") if tag.strip()]

    def get_absolute_url(self) -> str:
        return reverse("front:article_detail", kwargs={"slug": self.slug})


class News(models.Model):
    title = models.CharField("Заголовок", max_length=220)
    slug = models.SlugField("Slug", max_length=240, unique=True)
    category = models.ForeignKey(
        NewsCategory,
        on_delete=models.SET_NULL,
        related_name="news",
        verbose_name="Категория",
        blank=True,
        null=True,
    )
    description = models.TextField("Краткое описание", max_length=700)
    image = models.ImageField("Изображение", upload_to="news/%Y/%m/", blank=True, null=True)
    reading_time_minutes = models.PositiveSmallIntegerField("Время чтения, мин", default=3)
    tags = models.CharField("Теги", max_length=300, blank=True, help_text="Через запятую")
    is_main = models.BooleanField("Главная новость", default=False, db_index=True)
    content = HTMLField("Контент")
    is_published = models.BooleanField("Опубликована", default=True, db_index=True)
    created_at = models.DateTimeField("Создана", auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField("Обновлена", auto_now=True)

    class Meta:
        verbose_name = "Новость"
        verbose_name_plural = "Новости"
        ordering = ("-created_at", "-id")
        constraints = [
            models.UniqueConstraint(
                fields=("is_main",),
                condition=models.Q(is_main=True),
                name="unique_main_news",
            )
        ]

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.is_main:
                type(self).objects.filter(is_main=True).exclude(pk=self.pk).update(is_main=False)
            return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.title

    @property
    def tag_list(self) -> list[str]:
        return [tag.strip() for tag in self.tags.split(",") if tag.strip()]

    def get_absolute_url(self) -> str:
        return reverse("front:news_detail", kwargs={"slug": self.slug})


class StaticPage(models.Model):
    title = models.CharField("Заголовок", max_length=180)
    slug = models.SlugField("Slug", max_length=200, unique=True)
    content = HTMLField("Содержание")
    is_published = models.BooleanField("Опубликована", default=True, db_index=True)
    show_in_footer = models.BooleanField("Показывать в футере", default=True, db_index=True)
    footer_order = models.PositiveSmallIntegerField("Порядок в футере", default=100)
    created_at = models.DateTimeField("Создана", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлена", auto_now=True)

    class Meta:
        verbose_name = "Статическая страница"
        verbose_name_plural = "Статические страницы"
        ordering = ("footer_order", "title")

    def __str__(self) -> str:
        return self.title

    def get_absolute_url(self) -> str:
        return reverse("front:static_page", kwargs={"slug": self.slug})


class WikiVideoSection(models.Model):
    ICON_GENERAL = "general"
    ICON_ACCOUNT = "account"
    ICON_PREDICTIONS = "predictions"
    ICON_COPYBETTING = "copybetting"
    ICON_NOTIFICATIONS = "notifications"
    ICON_TELEGRAM = "telegram"

    ICON_CHOICES = (
        (ICON_GENERAL, "Общее"),
        (ICON_ACCOUNT, "Аккаунт"),
        (ICON_PREDICTIONS, "Прогнозы"),
        (ICON_COPYBETTING, "Копибеттинг"),
        (ICON_NOTIFICATIONS, "Уведомления"),
        (ICON_TELEGRAM, "Telegram"),
    )

    name = models.CharField("Название", max_length=160, unique=True)
    icon = models.CharField("Иконка", max_length=24, choices=ICON_CHOICES, default=ICON_GENERAL)
    is_active = models.BooleanField("Активен", default=True, db_index=True)
    sort_order = models.PositiveSmallIntegerField("Порядок", default=100, db_index=True)

    class Meta:
        verbose_name = "Wiki: раздел видео"
        verbose_name_plural = "Wiki: разделы видео"
        ordering = ("sort_order", "name", "id")

    def __str__(self) -> str:
        return self.name


class WikiVideo(models.Model):
    title = models.CharField("Название", max_length=220)
    section = models.ForeignKey(
        WikiVideoSection,
        on_delete=models.PROTECT,
        related_name="videos",
        verbose_name="Раздел",
    )
    description = models.TextField("Краткое описание", max_length=700)
    video = models.FileField("Видео", upload_to="wiki/videos/%Y/%m/")
    preview_image = models.ImageField(
        "Preview image",
        upload_to="wiki/previews/%Y/%m/",
        blank=True,
        null=True,
    )
    duration = models.CharField("Длительность", max_length=12, blank=True, help_text="Например: 5:18")
    is_published = models.BooleanField("Опубликовано", default=True, db_index=True)
    sort_order = models.PositiveSmallIntegerField("Порядок", default=100, db_index=True)
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        verbose_name = "Wiki: видео"
        verbose_name_plural = "Wiki: видео"
        ordering = ("section_id", "sort_order", "title", "id")

    def __str__(self) -> str:
        return self.title


class WikiTermSection(models.Model):
    ICON_GENERAL = "general"
    ICON_ACCOUNT = "account"
    ICON_BETS = "bets"
    ICON_ODDS = "odds"
    ICON_STATS = "stats"
    ICON_SUBSCRIPTIONS = "subscriptions"
    ICON_COPYBETTING = "copybetting"
    ICON_BALANCE = "balance"
    ICON_TOURNAMENTS = "tournaments"

    ICON_CHOICES = (
        (ICON_GENERAL, "Другое"),
        (ICON_ACCOUNT, "Аккаунт"),
        (ICON_BETS, "Ставки"),
        (ICON_ODDS, "Коэффициенты"),
        (ICON_STATS, "Статистика"),
        (ICON_SUBSCRIPTIONS, "Подписки"),
        (ICON_COPYBETTING, "Копибеттинг"),
        (ICON_BALANCE, "Баланс"),
        (ICON_TOURNAMENTS, "Турниры"),
    )

    ACCENT_BLUE = "blue"
    ACCENT_YELLOW = "yellow"
    ACCENT_SLATE = "slate"
    ACCENT_LIGHT = "light"

    ACCENT_CHOICES = (
        (ACCENT_BLUE, "Синий"),
        (ACCENT_YELLOW, "Жёлтый"),
        (ACCENT_SLATE, "Серый"),
        (ACCENT_LIGHT, "Светлый"),
    )

    name = models.CharField("Название", max_length=160, unique=True)
    icon = models.CharField("Иконка", max_length=24, choices=ICON_CHOICES, default=ICON_GENERAL)
    accent = models.CharField("Цвет", max_length=16, choices=ACCENT_CHOICES, default=ACCENT_BLUE)
    is_active = models.BooleanField("Активен", default=True, db_index=True)
    sort_order = models.PositiveSmallIntegerField("Порядок", default=100, db_index=True)

    class Meta:
        verbose_name = "Wiki: раздел терминов"
        verbose_name_plural = "Wiki: разделы терминов"
        ordering = ("sort_order", "name", "id")

    def __str__(self) -> str:
        return self.name


class WikiTerm(models.Model):
    ICON_USER = "user"
    ICON_GROUP = "group"
    ICON_COINS = "coins"
    ICON_CHART = "chart"
    ICON_COPY = "copy"
    ICON_LOCK = "lock"
    ICON_STAR = "star"
    ICON_BELL = "bell"
    ICON_CHECK = "check"
    ICON_TROPHY = "trophy"
    ICON_GAMEPAD = "gamepad"
    ICON_PERCENT = "percent"
    ICON_WALLET = "wallet"
    ICON_INFO = "info"

    ICON_CHOICES = (
        (ICON_USER, "Пользователь"),
        (ICON_GROUP, "Пользователи"),
        (ICON_COINS, "Монеты"),
        (ICON_CHART, "Статистика"),
        (ICON_COPY, "Копирование"),
        (ICON_LOCK, "Закрытый прогноз"),
        (ICON_STAR, "Избранное"),
        (ICON_BELL, "Уведомления"),
        (ICON_CHECK, "Проверка"),
        (ICON_TROPHY, "Турнир"),
        (ICON_GAMEPAD, "Ставка"),
        (ICON_PERCENT, "Коэффициент"),
        (ICON_WALLET, "Баланс"),
        (ICON_INFO, "Информация"),
    )

    term = models.CharField("Термин", max_length=180, unique=True)
    section = models.ForeignKey(
        WikiTermSection,
        on_delete=models.PROTECT,
        related_name="terms",
        verbose_name="Раздел",
    )
    icon = models.CharField("Иконка", max_length=24, choices=ICON_CHOICES, default=ICON_INFO)
    description = models.TextField("Описание")
    is_published = models.BooleanField("Опубликовано", default=True, db_index=True)
    sort_order = models.PositiveSmallIntegerField("Порядок", default=100, db_index=True)
    created_at = models.DateTimeField("Создано", auto_now_add=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        verbose_name = "Wiki: термин"
        verbose_name_plural = "Wiki: словарь"
        ordering = ("section_id", "sort_order", "term", "id")

    def __str__(self) -> str:
        return self.term


class PredictionLike(models.Model):
    prediction = models.ForeignKey(
        PredictionCoupon,
        on_delete=models.CASCADE,
        related_name="likes",
        verbose_name="Прогноз",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="prediction_likes",
        verbose_name="Пользователь",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("prediction", "user"),
                name="unique_prediction_like",
            )
        ]
        indexes = [
            models.Index(fields=("prediction", "created_at"), name="pred_like_pred_created_idx"),
            models.Index(fields=("user", "created_at"), name="pred_like_user_created_idx"),
        ]
        ordering = ("-created_at",)

    def clean(self):
        super().clean()
        _validate_not_own_prediction_reaction(
            prediction_id=self.prediction_id,
            user_id=self.user_id,
        )

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.user} 👍 {self.prediction_id}"


class PredictionFavorite(models.Model):
    prediction = models.ForeignKey(
        PredictionCoupon,
        on_delete=models.CASCADE,
        related_name="favorites",
        verbose_name="Прогноз",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="prediction_favorites",
        verbose_name="Пользователь",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("prediction", "user"),
                name="unique_prediction_favorite",
            )
        ]
        indexes = [
            models.Index(fields=("user", "created_at"), name="pred_fav_user_created_idx"),
        ]
        ordering = ("-created_at",)

    def clean(self):
        super().clean()
        _validate_not_own_prediction_reaction(
            prediction_id=self.prediction_id,
            user_id=self.user_id,
        )

    def save(self, *args, **kwargs):
        self.clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.user} ♥ {self.prediction_id}"
