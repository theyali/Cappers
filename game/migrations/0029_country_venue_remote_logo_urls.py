from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("game", "0028_team_league_local_logos"),
    ]

    operations = [
        migrations.RenameField(
            model_name="country",
            old_name="logo",
            new_name="remote_logo_url",
        ),
        migrations.RenameField(
            model_name="venue",
            old_name="logo",
            new_name="remote_logo_url",
        ),
    ]
