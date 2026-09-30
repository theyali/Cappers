from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cabinet", "0055_vipplan_icon_is_featured"),
    ]

    operations = [
        migrations.AddField(
            model_name="vipplan",
            name="description",
            field=models.TextField(blank=True, verbose_name="Описание"),
        ),
    ]
