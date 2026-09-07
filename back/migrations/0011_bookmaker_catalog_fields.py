from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("back", "0010_footer_content"),
    ]

    operations = [
        migrations.AddField(
            model_name="bookmaker",
            name="bonus_link",
            field=models.URLField(blank=True, max_length=500, verbose_name="Ссылка кнопки бонуса"),
        ),
        migrations.AddField(
            model_name="bookmaker",
            name="category",
            field=models.CharField(
                choices=[
                    ("standard", "Обычная"),
                    ("reliable", "Надёжная"),
                    ("popular", "Популярная"),
                    ("newbie", "Для новичков"),
                ],
                default="standard",
                max_length=32,
                verbose_name="Категория",
            ),
        ),
        migrations.AddField(
            model_name="bookmaker",
            name="advantages",
            field=models.TextField(blank=True, verbose_name="Преимущества (по одному в строке)"),
        ),
        migrations.AddField(
            model_name="bookmaker",
            name="payout_speed",
            field=models.CharField(blank=True, max_length=120, verbose_name="Скорость выплат"),
        ),
        migrations.AddField(
            model_name="bookmaker",
            name="payout_speed_note",
            field=models.CharField(blank=True, max_length=160, verbose_name="Подпись скорости выплат"),
        ),
        migrations.AddField(
            model_name="bookmaker",
            name="has_mobile_app",
            field=models.BooleanField(default=False, verbose_name="Есть мобильное приложение"),
        ),
        migrations.AddField(
            model_name="bookmaker",
            name="mobile_ios",
            field=models.BooleanField(default=False, verbose_name="iOS"),
        ),
        migrations.AddField(
            model_name="bookmaker",
            name="mobile_android",
            field=models.BooleanField(default=False, verbose_name="Android"),
        ),
        migrations.AddField(
            model_name="bookmaker",
            name="is_reliable",
            field=models.BooleanField(default=True, verbose_name="Надёжный"),
        ),
        migrations.AddField(
            model_name="bookmaker",
            name="is_popular",
            field=models.BooleanField(default=False, verbose_name="Популярный"),
        ),
        migrations.AddField(
            model_name="bookmaker",
            name="for_beginners",
            field=models.BooleanField(default=False, verbose_name="Для новичков"),
        ),
    ]
