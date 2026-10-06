from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("tournaments", "0010_tournament_reward_coins_wallet_text_and_more"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="tournamentprize",
            options={
                "ordering": ("tournament", "place", "sort_order", "id"),
                "verbose_name": "Приз турнира",
                "verbose_name_plural": "Призы турниров",
            },
        ),
    ]
