from django.db import migrations


def seed_filtered_match_list_seo(apps, schema_editor):
    PageSEO = apps.get_model("pages", "PageSEO")
    PageSEO.objects.update_or_create(
        route_name="game:match_list_filtered",
        exact_path="",
        defaults={
            "name": "Список матчей по фильтрам",
            "meta_title": "Матчи — расписание и данные | КапперХаб",
            "meta_description": (
                "Список спортивных матчей со статусами, временем начала, "
                "выбором спорта и основной информацией."
            ),
            "robots": "index,follow",
            "is_active": True,
        },
    )


def reverse_filtered_match_list_seo(apps, schema_editor):
    PageSEO = apps.get_model("pages", "PageSEO")
    PageSEO.objects.filter(route_name="game:match_list_filtered", exact_path="").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("pages", "0004_rename_match_list_seo"),
    ]

    operations = [
        migrations.RunPython(seed_filtered_match_list_seo, reverse_filtered_match_list_seo),
    ]
