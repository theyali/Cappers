from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Bookmaker",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=120, verbose_name="Название")),
                (
                    "icon",
                    models.ImageField(
                        blank=True,
                        upload_to="bookmakers/",
                        verbose_name="Иконка",
                    ),
                ),
                (
                    "bonus_text",
                    models.CharField(
                        blank=True,
                        max_length=160,
                        verbose_name="Текст бонуса",
                    ),
                ),
                ("link", models.URLField(max_length=500, verbose_name="Ссылка")),
                (
                    "exclusive",
                    models.BooleanField(default=False, verbose_name="Эксклюзивно"),
                ),
                (
                    "order",
                    models.PositiveIntegerField(
                        db_index=True,
                        default=0,
                        verbose_name="Порядок",
                    ),
                ),
            ],
            options={
                "verbose_name": "Букмекер",
                "verbose_name_plural": "Букмекеры",
                "ordering": ("order", "id"),
            },
        ),
        migrations.CreateModel(
            name="SiteSettings",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "telegram_bot_url",
                    models.URLField(
                        blank=True,
                        max_length=500,
                        verbose_name="Ссылка на Telegram-бота",
                    ),
                ),
            ],
            options={
                "verbose_name": "Настройки сайта",
                "verbose_name_plural": "Настройки сайта",
            },
        ),
    ]
