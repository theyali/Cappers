from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("game", "0011_matchodds_btts_all_matchodds_double_chance_all_and_more"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="predictioncoupon",
            name="title",
        ),
    ]
