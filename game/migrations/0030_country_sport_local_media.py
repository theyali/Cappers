import game.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("game", "0029_country_venue_remote_logo_urls"),
    ]

    operations = [
        migrations.RenameField(
            model_name="sport",
            old_name="image",
            new_name="remote_image_url",
        ),
        migrations.AddField(
            model_name="country",
            name="logo",
            field=models.ImageField(
                blank=True,
                upload_to=game.models.country_logo_upload_path,
            ),
        ),
        migrations.AddField(
            model_name="sport",
            name="image",
            field=models.ImageField(
                blank=True,
                upload_to=game.models.sport_image_upload_path,
            ),
        ),
    ]
