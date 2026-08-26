from django.db import models


class Bookmaker(models.Model):
    name = models.CharField("Название", max_length=120)
    icon = models.ImageField("Иконка", upload_to="bookmakers/", blank=True)
    bonus_text = models.CharField("Текст бонуса", max_length=160, blank=True)
    link = models.URLField("Ссылка", max_length=500)
    exclusive = models.BooleanField("Эксклюзивно", default=False)
    order = models.PositiveIntegerField("Порядок", default=0, db_index=True)

    class Meta:
        verbose_name = "Букмекер"
        verbose_name_plural = "Букмекеры"
        ordering = ("order", "id")

    def __str__(self) -> str:
        return self.name


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
