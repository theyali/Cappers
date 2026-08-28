from django.db import migrations, models


SIDEBAR_ROUTES = (
    "front:cappers_stats",
    "game:match_list",
    "game:match_detail",
)


def set_sidebar_placements(apps, schema_editor):
    PageSEO = apps.get_model("pages", "PageSEO")
    PageSEO.objects.filter(route_name__in=SIDEBAR_ROUTES).update(adv_placement="sidebar")


class Migration(migrations.Migration):
    dependencies = [
        ("pages", "0002_seed_page_seo"),
    ]

    operations = [
        migrations.CreateModel(
            name="AdvBanner",
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
                ("name", models.CharField(max_length=160, verbose_name="Название в админке")),
                (
                    "size",
                    models.CharField(
                        choices=[
                            ("full_240", "На всю ширину · 240 px"),
                            ("half_240", "Половина ширины · 240 px"),
                            ("full_450", "На всю ширину · 450 px"),
                            ("half_450", "Половина ширины · 450 px"),
                        ],
                        default="full_240",
                        max_length=20,
                        verbose_name="Размер",
                    ),
                ),
                ("image", models.ImageField(upload_to="ads/", verbose_name="Изображение")),
                (
                    "mobile_image",
                    models.ImageField(
                        blank=True,
                        help_text="Если заполнено, используется на экранах до 767 px.",
                        upload_to="ads/mobile/",
                        verbose_name="Мобильное изображение",
                    ),
                ),
                ("url", models.URLField(max_length=1000, verbose_name="Ссылка")),
            ],
            options={
                "verbose_name": "Рекламный баннер",
                "verbose_name_plural": "Рекламные баннеры",
                "ordering": ("id",),
            },
        ),
        migrations.AddField(
            model_name="pageseo",
            name="adv_placement",
            field=models.CharField(
                choices=[("content", "На странице"), ("sidebar", "В сайдбаре")],
                default="content",
                help_text="Для страниц с сайдбаром выберите размещение в сайдбаре.",
                max_length=16,
                verbose_name="Размещение рекламы",
            ),
        ),
        migrations.AddField(
            model_name="pageseo",
            name="adv_banners",
            field=models.ManyToManyField(
                blank=True,
                related_name="pages",
                to="pages.advbanner",
                verbose_name="Рекламные баннеры",
            ),
        ),
        migrations.RunPython(set_sidebar_placements, migrations.RunPython.noop),
    ]
