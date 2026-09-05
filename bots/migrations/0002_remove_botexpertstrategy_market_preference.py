from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("bots", "0001_initial"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="botexpertstrategy",
            name="market_preference",
        ),
    ]
