from django.db import migrations, models


def copy_website_settings(apps, schema_editor):
    FrontWebsiteSettings = apps.get_model("front", "WebsiteSettings")
    BackWebsiteSettings = apps.get_model("back", "WebsiteSettings")
    SiteSettings = apps.get_model("back", "SiteSettings")

    front_settings = FrontWebsiteSettings.objects.filter(pk=1).first()
    old_site_settings = SiteSettings.objects.filter(pk=1).first()

    site_name = "КапперХаб"
    fixed_tg_enable = False
    fixed_tg_link = ""
    fixed_tg_title = "Бесплатный прогноз в Telegram"

    if front_settings is not None:
        site_name = front_settings.site_name or site_name
        fixed_tg_enable = front_settings.fixed_tg_enable
        fixed_tg_link = front_settings.fixed_tg_link or ""
        fixed_tg_title = front_settings.fixed_tg_title or fixed_tg_title

    if old_site_settings is not None and old_site_settings.telegram_bot_url and not fixed_tg_link:
        fixed_tg_link = old_site_settings.telegram_bot_url

    BackWebsiteSettings.objects.update_or_create(
        pk=1,
        defaults={
            "site_name": site_name,
            "fixed_tg_enable": fixed_tg_enable,
            "fixed_tg_link": fixed_tg_link,
            "fixed_tg_title": fixed_tg_title,
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ("back", "0001_initial"),
        ("front", "0003_staticpage_websitesettings"),
    ]

    operations = [
        migrations.CreateModel(
            name="WebsiteSettings",
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
                    "site_name",
                    models.CharField(
                        default="КапперХаб",
                        max_length=120,
                        verbose_name="Название сайта",
                    ),
                ),
                (
                    "fixed_tg_enable",
                    models.BooleanField(
                        default=False,
                        verbose_name="Показывать Telegram-баннер",
                    ),
                ),
                (
                    "fixed_tg_link",
                    models.URLField(
                        blank=True,
                        max_length=500,
                        verbose_name="Ссылка Telegram",
                    ),
                ),
                (
                    "fixed_tg_title",
                    models.CharField(
                        blank=True,
                        default="Бесплатный прогноз в Telegram",
                        max_length=120,
                        verbose_name="Текст Telegram-баннера",
                    ),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True, verbose_name="Обновлено"),
                ),
            ],
            options={
                "verbose_name": "Настройки сайта",
                "verbose_name_plural": "Настройки сайта",
            },
        ),
        migrations.RunPython(copy_website_settings, migrations.RunPython.noop),
        migrations.DeleteModel(name="SiteSettings"),
    ]
