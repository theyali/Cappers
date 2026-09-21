import game.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("game", "0027_league_top_flags"),
    ]

    operations = [
        migrations.RenameField(
            model_name="league",
            old_name="logo",
            new_name="remote_logo_url",
        ),
        migrations.RenameField(
            model_name="team",
            old_name="logo",
            new_name="remote_logo_url",
        ),
        migrations.AddField(
            model_name="league",
            name="logo",
            field=models.ImageField(
                blank=True,
                upload_to=game.models.league_logo_upload_path,
            ),
        ),
        migrations.AddField(
            model_name="team",
            name="logo",
            field=models.ImageField(
                blank=True,
                upload_to=game.models.team_logo_upload_path,
            ),
        ),
    ]
