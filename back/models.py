from django.db import models


class Bookmaker(models.Model):
    name = models.CharField("Название", max_length=120)
    icon = models.ImageField("Иконка", upload_to="bookmakers/", blank=True)
    bonus_text = models.CharField("Текст бонуса", max_length=160, blank=True)
    description = models.CharField("Краткое описание", max_length=220, blank=True)
    link = models.URLField("Ссылка", max_length=500)
    exclusive = models.BooleanField("Эксклюзивно", default=False)
    show_on_home = models.BooleanField("Показывать на главной", default=False)
    home_order = models.PositiveIntegerField("Порядок на главной", default=0, db_index=True)
    order = models.PositiveIntegerField("Порядок", default=0, db_index=True)

    class Meta:
        verbose_name = "Букмекер"
        verbose_name_plural = "Букмекеры"
        ordering = ("order", "id")

    def __str__(self) -> str:
        return self.name


class Bonus(models.Model):
    bookmaker = models.ForeignKey(
        Bookmaker,
        verbose_name="Букмекер",
        on_delete=models.CASCADE,
        related_name="bonuses",
    )
    promocode = models.CharField("Промокод", max_length=120, blank=True)
    short_description = models.CharField("Краткое описание", max_length=220)
    description = models.TextField("Описание", blank=True)
    link = models.URLField("Ссылка", max_length=500)
    order = models.PositiveIntegerField("Порядок", default=0, db_index=True)

    class Meta:
        verbose_name = "Бонус"
        verbose_name_plural = "Бонусы"
        ordering = ("order", "id")

    def __str__(self) -> str:
        return f"{self.bookmaker.name} — {self.short_description}"


class WebsiteSettings(models.Model):
    site_name = models.CharField("Название сайта", max_length=120, default="КапперХаб")
    fixed_tg_enable = models.BooleanField("Показывать Telegram-баннер", default=False)
    fixed_tg_link = models.URLField("Ссылка Telegram", max_length=500, blank=True)
    fixed_tg_title = models.CharField(
        "Текст Telegram-баннера",
        max_length=120,
        default="Бесплатный прогноз в Telegram",
        blank=True,
    )

    match_bookmaker = models.ForeignKey(
        Bookmaker,
        verbose_name="Матч — БК",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    prediction_bookmaker = models.ForeignKey(
        Bookmaker,
        verbose_name="Прогнозы — БК",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    home_about_enabled = models.BooleanField("Показывать блок «О нас» на главной", default=True)
    home_about_eyebrow = models.CharField(
        "Надпись над заголовком",
        max_length=80,
        default="О компании",
        blank=True,
    )
    home_about_title = models.CharField(
        "Заголовок блока",
        max_length=220,
        default="КапперХаб — спортивная аналитика в одном месте",
        blank=True,
    )
    home_about_intro = models.TextField(
        "Короткое описание",
        default=(
            "Мы собираем матчи, статистику, экспертные материалы и спортивный контент "
            "в одном понятном интерфейсе."
        ),
        blank=True,
    )
    home_about_text = models.TextField(
        "Основной текст о компании",
        default=(
            "КапперХаб — информационная платформа для аудитории, которая следит за спортом "
            "и хочет быстрее находить данные, мнения авторов и разборы матчей. Мы развиваем "
            "публичные профили экспертов, ленты материалов, рейтинги и удобные страницы матчей, "
            "чтобы важная информация была доступна в одном месте."
        ),
        blank=True,
    )
    home_about_seo_title = models.CharField(
        "SEO-заголовок внутри блока",
        max_length=220,
        default="Спортивные матчи, аналитика, эксперты и статьи",
        blank=True,
    )
    home_about_seo_text = models.TextField(
        "SEO-текст на главной",
        default=(
            "На КапперХаб можно изучать расписание и карточки спортивных матчей, читать аналитические "
            "материалы, сравнивать публичные профили авторов и следить за обновлениями спортивной ленты. "
            "Структура сайта помогает быстро переходить между матчами, экспертами, статистикой и статьями."
        ),
        blank=True,
    )
    home_about_fact_1_title = models.CharField(
        "Карточка 1 — заголовок",
        max_length=80,
        default="Матчи и данные",
        blank=True,
    )
    home_about_fact_1_text = models.CharField(
        "Карточка 1 — текст",
        max_length=220,
        default="Расписание, статусы матчей и ключевая информация в одном интерфейсе.",
        blank=True,
    )
    home_about_fact_2_title = models.CharField(
        "Карточка 2 — заголовок",
        max_length=80,
        default="Публичные эксперты",
        blank=True,
    )
    home_about_fact_2_text = models.CharField(
        "Карточка 2 — текст",
        max_length=220,
        default="Профили авторов, статистика активности, достижения и подписки.",
        blank=True,
    )
    home_about_fact_3_title = models.CharField(
        "Карточка 3 — заголовок",
        max_length=80,
        default="Спортивный контент",
        blank=True,
    )
    home_about_fact_3_text = models.CharField(
        "Карточка 3 — текст",
        max_length=220,
        default="Статьи, разборы и материалы редакции для спортивной аудитории.",
        blank=True,
    )

    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        verbose_name = "Настройки сайта"
        verbose_name_plural = "Настройки сайта"

    def __str__(self) -> str:
        return self.site_name

    @classmethod
    def load(cls):
        settings, _ = cls.objects.get_or_create(pk=1)
        return settings
