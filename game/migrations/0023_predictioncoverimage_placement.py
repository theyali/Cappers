from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("game", "0022_predictioncoverimage_predictioncoupon_cover_image_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="predictioncoverimage",
            name="placement",
            field=models.CharField(
                choices=[
                    ("grid", "Для обычной прогнозной сетки"),
                    ("home_slider", "Для слайдера в главной"),
                ],
                db_index=True,
                default="grid",
                max_length=20,
                verbose_name="Размещение",
            ),
        ),
        migrations.AlterModelOptions(
            name="predictioncoverimage",
            options={
                "ordering": [
                    "placement",
                    "cover_type",
                    "sport__name_ru",
                    "sport__name",
                    "-created_at",
                ],
                "verbose_name": "Обложка прогноза",
                "verbose_name_plural": "Обложки прогнозов",
            },
        ),
    ]
