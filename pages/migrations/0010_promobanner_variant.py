from django.db import migrations, models


def set_existing_promo_variants(apps, schema_editor):
    PromoBanner = apps.get_model("pages", "PromoBanner")

    for banner in PromoBanner.objects.all().iterator(chunk_size=100):
        placements = set(
            banner.page_placements.values_list("placement", flat=True)
        )
        if placements and "center" not in placements:
            banner.variant = "sidebar_medium"
        else:
            banner.variant = "center_wide"
        banner.save(update_fields=["variant"])


class Migration(migrations.Migration):

    dependencies = [
        ("pages", "0009_promo_banner_placements"),
    ]

    operations = [
        migrations.AddField(
            model_name="promobanner",
            name="variant",
            field=models.CharField(
                choices=[
                    ("sidebar_small", "Sidebar · маленький"),
                    ("sidebar_medium", "Sidebar · средний"),
                    ("sidebar_tall", "Sidebar · высокий"),
                    ("center_wide", "Центр · широкий"),
                    ("center_compact", "Центр · компактный"),
                    ("feed_inline", "Лента · inline"),
                ],
                db_index=True,
                default="center_wide",
                max_length=24,
                verbose_name="Размер баннера",
            ),
        ),
        migrations.RunPython(set_existing_promo_variants, migrations.RunPython.noop),
    ]
