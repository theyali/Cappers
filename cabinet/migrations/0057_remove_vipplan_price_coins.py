from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("cabinet", "0056_vipplan_description"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="vipplan",
            name="price_coins",
        ),
    ]
