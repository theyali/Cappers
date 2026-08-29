from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cabinet", "0017_userpresence"),
    ]

    operations = [
        migrations.AddField(
            model_name="analystprofile",
            name="is_vip",
            field=models.BooleanField(
                db_index=True,
                default=False,
                verbose_name="VIP прогнозист",
            ),
        ),
    ]
