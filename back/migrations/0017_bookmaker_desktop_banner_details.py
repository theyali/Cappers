from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("back", "0016_bookmaker_slider_img"),
    ]

    operations = [
        migrations.AddField(
            model_name="bookmaker",
            name="desktop_banner_img",
            field=models.ImageField(
                blank=True,
                upload_to="bookmakers/desktop/",
                verbose_name="Фон большого баннера на ПК",
            ),
        ),
        migrations.AddField(
            model_name="bookmaker",
            name="rating",
            field=models.DecimalField(
                blank=True,
                decimal_places=1,
                max_digits=2,
                null=True,
                validators=[MinValueValidator(0), MaxValueValidator(5)],
                verbose_name="Оценка для главной",
            ),
        ),
        migrations.AddField(
            model_name="bookmaker",
            name="minimum_deposit",
            field=models.CharField(
                blank=True,
                max_length=80,
                verbose_name="Минимальный депозит",
            ),
        ),
        migrations.AddField(
            model_name="bookmaker",
            name="bonus_updated_at",
            field=models.DateField(
                blank=True,
                null=True,
                verbose_name="Дата обновления бонуса",
            ),
        ),
    ]
