from django.db import migrations


def seed_about_page_seo(apps, schema_editor):
    PageSEO = apps.get_model("pages", "PageSEO")
    PageSEO.objects.get_or_create(
        route_name="front:about",
        exact_path="",
        defaults={
            "name": "О нас",
            "meta_title": "О нас — КапперХаб",
            "meta_description": (
                "КапперХаб собирает матчи, прогнозы и статистику капперов "
                "с открытой историей результатов."
            ),
            "robots": "index,follow",
            "adv_placement": "sidebar",
            "schema_type": "AboutPage",
            "is_active": True,
        },
    )


def remove_about_page_seo(apps, schema_editor):
    PageSEO = apps.get_model("pages", "PageSEO")
    PageSEO.objects.filter(route_name="front:about", exact_path="").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("pages", "0011_promobanner_audience"),
    ]

    operations = [
        migrations.RunPython(seed_about_page_seo, remove_about_page_seo),
    ]
