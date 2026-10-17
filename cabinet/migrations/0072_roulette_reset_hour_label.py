import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cabinet", "0071_preset_avatar"),
    ]

    operations = [
        migrations.AlterField(
            model_name="roulettesettings",
            name="reset_hour",
            field=models.PositiveSmallIntegerField(
                default=0,
                help_text="Используется для суточных лимитов выдачи призов. Бесплатные попытки доступны через 24 часа после последней прокрутки независимо от этого часа.",
                validators=[
                    django.core.validators.MinValueValidator(0),
                    django.core.validators.MaxValueValidator(23),
                ],
                verbose_name="Час обновления суточных лимитов призов",
            ),
        ),
    ]
