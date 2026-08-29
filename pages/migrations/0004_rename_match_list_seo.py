from django.db import migrations


def rename_match_list_seo(apps, schema_editor):
    PageSEO = apps.get_model("pages", "PageSEO")
    PageSEO.objects.update_or_create(
        route_name="game:match_list",
        exact_path="",
        defaults={
            "name": "Список матчей",
            "meta_title": "Матчи — расписание и данные | КапперХаб",
            "meta_description": (
                "Список спортивных матчей со статусами, временем начала, "
                "выбором спорта и основной информацией."
            ),
            "robots": "index,follow",
            "is_active": True,
        },
    )


def reverse_match_list_seo(apps, schema_editor):
    PageSEO = apps.get_model("pages", "PageSEO")
    PageSEO.objects.filter(route_name="game:match_list", exact_path="").update(
        meta_title="Футбольные матчи — расписание и данные | КапперХаб",
        meta_description="Список футбольных матчей со статусами, временем начала и основной информацией.",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("pages", "0003_advbanner_page_advertising"),
    ]

    operations = [
        migrations.RunPython(rename_match_list_seo, reverse_match_list_seo),
    ]
