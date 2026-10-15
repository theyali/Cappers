from django.db import migrations, models


def seed_bookmakers(apps, schema_editor):
    Bookmaker = apps.get_model("game", "ComparisonBookmaker")
    Odds = apps.get_model("game", "MatchBookmakerOdds")
    alias = schema_editor.connection.alias
    for name in Odds.objects.using(alias).values_list("name", flat=True).distinct():
        Bookmaker.objects.using(alias).get_or_create(
            key=" ".join(name.casefold().split()), defaults={"name": name},
        )


class Migration(migrations.Migration):
    dependencies = [("game", "0041_full_bookmaker_odds")]

    operations = [
        migrations.CreateModel(
            name="ComparisonBookmaker",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(editable=False, max_length=320, unique=True, verbose_name="Имя из API (ключ)")),
                ("name", models.CharField(max_length=160, verbose_name="Название")),
                ("icon", models.ImageField(blank=True, upload_to="game/bookmakers/", verbose_name="Иконка")),
            ],
            options={"verbose_name": "Букмекер сравнения", "verbose_name_plural": "Букмекеры сравнения", "ordering": ("name", "pk")},
        ),
        migrations.RunPython(seed_bookmakers, migrations.RunPython.noop),
    ]
