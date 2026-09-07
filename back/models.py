from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


PERCENT_VALIDATORS = [MinValueValidator(0), MaxValueValidator(100)]


class Bookmaker(models.Model):
    class Category(models.TextChoices):
        STANDARD = "standard", "Обычная"
        RELIABLE = "reliable", "Надёжная"
        POPULAR = "popular", "Популярная"
        NEWBIE = "newbie", "Для новичков"

    name = models.CharField("Название", max_length=120)
    icon = models.ImageField("Иконка", upload_to="bookmakers/", blank=True)
    bonus_text = models.CharField("Текст бонуса", max_length=160, blank=True)
    description = models.CharField("Краткое описание", max_length=220, blank=True)
    link = models.URLField("Ссылка", max_length=500)
    bonus_link = models.URLField("Ссылка кнопки бонуса", max_length=500, blank=True)
    category = models.CharField("Категория", max_length=32, choices=Category.choices, default=Category.STANDARD)
    advantages = models.TextField("Преимущества (по одному в строке)", blank=True)
    payout_speed = models.CharField("Скорость выплат", max_length=120, blank=True)
    payout_speed_note = models.CharField("Подпись скорости выплат", max_length=160, blank=True)
    has_mobile_app = models.BooleanField("Есть мобильное приложение", default=False)
    mobile_ios = models.BooleanField("iOS", default=False)
    mobile_android = models.BooleanField("Android", default=False)
    is_reliable = models.BooleanField("Надёжный", default=True)
    is_popular = models.BooleanField("Популярный", default=False)
    for_beginners = models.BooleanField("Для новичков", default=False)
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

    @property
    def advantages_list(self) -> list[str]:
        return [line.strip() for line in self.advantages.splitlines() if line.strip()]

    @property
    def mobile_platforms_label(self) -> str:
        platforms = []
        if self.mobile_ios:
            platforms.append("iOS")
        if self.mobile_android:
            platforms.append("Android")
        return ", ".join(platforms)

    @property
    def effective_bonus_link(self) -> str:
        return self.bonus_link or self.link


class Bonus(models.Model):
    bookmaker = models.ForeignKey(
        Bookmaker,
        verbose_name="Букмекер",
        on_delete=models.CASCADE,
        related_name="bonuses",
    )
    image = models.ImageField("Изображение", upload_to="bonuses/", blank=True)
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


class FooterLinkGroup(models.Model):
    title = models.CharField("Заголовок", max_length=120)
    order = models.PositiveIntegerField("Порядок", default=0, db_index=True)
    is_active = models.BooleanField("Активна", default=True, db_index=True)

    class Meta:
        verbose_name = "Футер — группа ссылок"
        verbose_name_plural = "Футер — группы ссылок"
        ordering = ("order", "id")

    def __str__(self) -> str:
        return self.title


class FooterLink(models.Model):
    group = models.ForeignKey(
        FooterLinkGroup,
        verbose_name="Группа",
        on_delete=models.CASCADE,
        related_name="links",
    )
    title = models.CharField("Текст", max_length=160)
    url = models.CharField("Ссылка", max_length=500)
    order = models.PositiveIntegerField("Порядок", default=0, db_index=True)
    is_active = models.BooleanField("Активна", default=True, db_index=True)

    class Meta:
        verbose_name = "Футер — ссылка"
        verbose_name_plural = "Футер — ссылки"
        ordering = ("group__order", "order", "id")

    def __str__(self) -> str:
        return self.title


class FooterButton(models.Model):
    class Kind(models.TextChoices):
        APP = "app", "Приложение"
        SOCIAL = "social", "Соцсеть"
        PARTNER = "partner", "Партнёр/логотип"

    kind = models.CharField("Тип", max_length=16, choices=Kind.choices, db_index=True)
    title = models.CharField("Текст", max_length=120)
    subtitle = models.CharField("Подпись", max_length=120, blank=True)
    url = models.CharField("Ссылка", max_length=500, blank=True)
    icon_text = models.CharField("Текстовая иконка", max_length=16, blank=True)
    icon = models.ImageField("Иконка", upload_to="footer/", blank=True)
    order = models.PositiveIntegerField("Порядок", default=0, db_index=True)
    is_active = models.BooleanField("Активен", default=True, db_index=True)

    class Meta:
        verbose_name = "Футер — кнопка/логотип"
        verbose_name_plural = "Футер — кнопки и логотипы"
        ordering = ("kind", "order", "id")

    def __str__(self) -> str:
        return self.title


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
    footer_description = models.TextField(
        "Футер — описание",
        default="Прогнозы на спорт, статистика капперов и история результатов в одном месте.",
        blank=True,
    )
    footer_age_label = models.CharField("Футер — возрастной знак", max_length=16, default="18+", blank=True)
    footer_responsible_text = models.TextField(
        "Футер — предупреждение",
        default="Материалы сайта носят информационный характер. Оценивайте риски и принимайте решения самостоятельно.",
        blank=True,
    )
    footer_support_title = models.CharField("Футер — заголовок поддержки", max_length=120, default="Поддержка 24/7", blank=True)
    footer_support_phone = models.CharField("Футер — телефон поддержки", max_length=80, blank=True)
    footer_support_email = models.EmailField("Футер — email поддержки", blank=True)
    footer_legal_text = models.TextField("Футер — юридический текст", default="Официальные документы сервиса", blank=True)
    footer_copyright_text = models.CharField("Футер — копирайт", max_length=220, default="© КапперХаб. Все права защищены.", blank=True)
    footer_disclaimer_text = models.CharField("Футер — дисклеймер", max_length=260, default="Сервис не гарантирует результат спортивных прогнозов.", blank=True)
    footer_address_text = models.TextField("Футер — адрес/реквизиты", blank=True)

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

    referral_subscription_percent = models.DecimalField(
        "Реферал — покупка подписки, %",
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=PERCENT_VALIDATORS,
    )
    referral_tournament_percent = models.DecimalField(
        "Реферал — приз турнира, %",
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=PERCENT_VALIDATORS,
    )
    referral_balance_topup_percent = models.DecimalField(
        "Реферал — пополнение баланса, %",
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=PERCENT_VALIDATORS,
    )

    platform_fee_1_day_percent = models.DecimalField(
        "Комиссия тарифа 1 день, %",
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=PERCENT_VALIDATORS,
    )
    platform_fee_7_days_percent = models.DecimalField(
        "Комиссия тарифа 7 дней, %",
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=PERCENT_VALIDATORS,
    )
    platform_fee_30_days_percent = models.DecimalField(
        "Комиссия тарифа 30 дней, %",
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=PERCENT_VALIDATORS,
    )
    platform_fee_90_days_percent = models.DecimalField(
        "Комиссия тарифа 3 месяца, %",
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=PERCENT_VALIDATORS,
    )
    platform_fee_180_days_percent = models.DecimalField(
        "Комиссия тарифа 6 месяцев, %",
        max_digits=5,
        decimal_places=2,
        default=0,
        validators=PERCENT_VALIDATORS,
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
