from django.db import migrations, models
import django.db.models.deletion


def copy_existing_promo_banners(apps, schema_editor):
    PageSEO = apps.get_model("pages", "PageSEO")
    PagePromoBanner = apps.get_model("pages", "PagePromoBanner")

    for page in PageSEO.objects.prefetch_related("promo_banners").iterator(chunk_size=100):
        default_placement = "right" if page.route_name == "front:index" else "center"
        rows = [
            PagePromoBanner(
                page_id=page.pk,
                banner_id=banner.pk,
                placement=default_placement,
                sort_order=index * 10,
            )
            for index, banner in enumerate(page.promo_banners.all(), start=1)
        ]
        PagePromoBanner.objects.bulk_create(rows, ignore_conflicts=True)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("pages", "0008_promobanner_optional_text_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="pageseo",
            name="layout_columns",
            field=models.CharField(
                choices=[
                    ("three", "3 колонки"),
                    ("left_center", "2 колонки: левый сайдбар + центр"),
                    ("center_right", "2 колонки: центр + правый сайдбар"),
                    ("center_only", "1 колонка: центр"),
                ],
                default="three",
                help_text="Используется общим layout CSS для страниц с predictions-layout.",
                max_length=24,
                verbose_name="Колонки страницы",
            ),
        ),
        migrations.CreateModel(
            name="PagePromoBanner",
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
                    "placement",
                    models.CharField(
                        choices=[
                            ("left", "Левый сайдбар"),
                            ("center", "Центр"),
                            ("right", "Правый сайдбар"),
                        ],
                        db_index=True,
                        default="center",
                        max_length=16,
                        verbose_name="Где показывать",
                    ),
                ),
                (
                    "sort_order",
                    models.PositiveSmallIntegerField(
                        db_index=True,
                        default=100,
                        verbose_name="Порядок",
                    ),
                ),
                (
                    "banner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="page_placements",
                        to="pages.promobanner",
                        verbose_name="Промо-баннер",
                    ),
                ),
                (
                    "page",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="promo_banner_placements",
                        to="pages.pageseo",
                        verbose_name="Страница",
                    ),
                ),
            ],
            options={
                "verbose_name": "Размещение промо-баннера",
                "verbose_name_plural": "Размещения промо-баннеров",
                "ordering": ("placement", "sort_order", "id"),
            },
        ),
        migrations.AddConstraint(
            model_name="pagepromobanner",
            constraint=models.UniqueConstraint(
                fields=("page", "banner", "placement"),
                name="pages_promo_placement_unique",
            ),
        ),
        migrations.AddIndex(
            model_name="pagepromobanner",
            index=models.Index(
                fields=("page", "placement", "sort_order"),
                name="pages_promo_place_order_idx",
            ),
        ),
        migrations.RunPython(copy_existing_promo_banners, noop_reverse),
    ]
