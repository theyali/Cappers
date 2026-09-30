from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cabinet", "0054_user_email_verified"),
    ]

    operations = [
        migrations.AddField(
            model_name="vipplan",
            name="icon",
            field=models.ImageField(
                blank=True,
                upload_to="vip_plans/icons/%Y/%m/",
                verbose_name="Иконка тарифа",
            ),
        ),
        migrations.AddField(
            model_name="vipplan",
            name="is_featured",
            field=models.BooleanField(
                db_index=True,
                default=False,
                verbose_name="Рекомендуем",
            ),
        ),
    ]
