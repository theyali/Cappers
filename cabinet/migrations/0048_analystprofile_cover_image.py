from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cabinet", "0047_xplevel_media_description"),
    ]

    operations = [
        migrations.AddField(
            model_name="analystprofile",
            name="cover_image",
            field=models.ImageField(
                blank=True,
                default="",
                upload_to="profile_covers/%Y/%m/",
                verbose_name="Обложка профиля",
            ),
            preserve_default=False,
        ),
    ]
