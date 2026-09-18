from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pages", "0010_promobanner_variant"),
    ]

    operations = [
        migrations.AddField(
            model_name="promobanner",
            name="audience",
            field=models.CharField(
                choices=[
                    ("all", "Всем"),
                    ("anonymous", "Только гостям"),
                    ("authenticated", "Авторизованным"),
                    ("reader", "Обычным пользователям"),
                    ("capper", "Капперам"),
                    ("vip_capper", "VIP-капперам"),
                    ("non_vip_capper", "Капперам без VIP"),
                ],
                db_index=True,
                default="all",
                max_length=24,
                verbose_name="Аудитория",
            ),
        ),
    ]
