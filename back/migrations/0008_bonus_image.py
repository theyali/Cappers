from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("back", "0007_bonus_model"),
    ]

    operations = [
        migrations.AddField(
            model_name="bonus",
            name="image",
            field=models.ImageField(blank=True, upload_to="bonuses/", verbose_name="Изображение"),
        ),
    ]
