from django.core.validators import RegexValidator
from django.db import migrations, models
import tournaments.models


class Migration(migrations.Migration):

    dependencies = [
        ("tournaments", "0013_tournament_finalized_at"),
    ]

    operations = [
        migrations.AddField(
            model_name="tournament",
            name="card_icon_bg_color",
            field=models.CharField(
                default="#09663F",
                max_length=7,
                validators=[RegexValidator(message="Укажите цвет в формате #RRGGBB.", regex="^#[0-9a-fA-F]{6}$")],
                verbose_name="Фон иконки в карточке",
            ),
        ),
        migrations.AddField(
            model_name="tournament",
            name="sponsor_name",
            field=models.CharField(blank=True, max_length=100, verbose_name="Имя спонсора"),
        ),
        migrations.AddField(
            model_name="tournament",
            name="sponsor_logo",
            field=models.ImageField(
                blank=True,
                null=True,
                upload_to=tournaments.models.tournament_image_upload_path,
                verbose_name="Логотип спонсора",
            ),
        ),
        migrations.AddField(
            model_name="tournament",
            name="sponsor_url",
            field=models.URLField(blank=True, max_length=500, verbose_name="Ссылка спонсора"),
        ),
    ]
