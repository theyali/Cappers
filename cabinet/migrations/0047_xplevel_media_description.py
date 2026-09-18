from django.db import migrations, models
import tinymce.models


class Migration(migrations.Migration):

    dependencies = [
        ("cabinet", "0046_referral_bonus_settings"),
    ]

    operations = [
        migrations.AddField(
            model_name="xplevel",
            name="description",
            field=tinymce.models.HTMLField(
                blank=True,
                default="",
                verbose_name="Описание",
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="xplevel",
            name="icon",
            field=models.ImageField(
                blank=True,
                default="",
                upload_to="xp_levels/icons/%Y/%m/",
                verbose_name="Иконка",
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="xplevel",
            name="image",
            field=models.ImageField(
                blank=True,
                default="",
                upload_to="xp_levels/images/%Y/%m/",
                verbose_name="Изображение",
            ),
            preserve_default=False,
        ),
    ]
