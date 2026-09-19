from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("game", "0024_performance_query_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="predictioncoupon",
            name="custom_cover_image",
            field=models.ImageField(
                blank=True,
                upload_to="prediction_covers/custom/%Y/%m/",
                verbose_name="Своя обложка",
            ),
        ),
        migrations.AddField(
            model_name="predictioncoupon",
            name="description",
            field=models.TextField(blank=True, verbose_name="Описание прогноза"),
        ),
        migrations.AddField(
            model_name="predictioncoupon",
            name="headline",
            field=models.CharField(blank=True, max_length=160, verbose_name="Заголовок"),
        ),
        migrations.AddField(
            model_name="predictioncoupon",
            name="prediction_format",
            field=models.CharField(
                choices=[
                    ("quick", "Быстрый купон"),
                    ("rich", "Расширенный прогноз"),
                ],
                db_index=True,
                default="quick",
                max_length=16,
                verbose_name="Формат прогноза",
            ),
        ),
        migrations.AddField(
            model_name="predictioncoupon",
            name="tags",
            field=models.JSONField(blank=True, default=list, verbose_name="Теги"),
        ),
    ]
