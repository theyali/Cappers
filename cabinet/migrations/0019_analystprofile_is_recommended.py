from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cabinet", "0018_analystprofile_is_vip"),
    ]

    operations = [
        migrations.AddField(
            model_name="analystprofile",
            name="is_recommended",
            field=models.BooleanField(
                db_index=True,
                default=False,
                verbose_name="Рекомендовать подписаться",
            ),
        ),
    ]
