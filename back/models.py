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


class SiteSettings(models.Model):
    telegram_bot_url = models.URLField(
        "Ссылка на Telegram-бота",
        max_length=500,
        blank=True,
    )

    class Meta:
        verbose_name = "Настройки сайта"
        verbose_name_plural = "Настройки сайта"

    def save(self, *args, **kwargs) -> None:
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def get_solo(cls):
        return cls.objects.filter(pk=1).first()

    def __str__(self) -> str:
        return "Настройки сайта"
