from django.db import migrations


def keep_existing_bookmaker_choices(apps, schema_editor):
    WebsiteSettings = apps.get_model("back", "WebsiteSettings")
    for settings in WebsiteSettings.objects.all():
        fields = []
        if not settings.match_detail_bookmaker_left_id and settings.match_detail_bookmaker_right_id:
            settings.match_detail_bookmaker_left_id = settings.match_detail_bookmaker_right_id
            fields.append("match_detail_bookmaker_left")
        if not settings.prediction_bookmaker_left_id and settings.prediction_bookmaker_right_id:
            settings.prediction_bookmaker_left_id = settings.prediction_bookmaker_right_id
            fields.append("prediction_bookmaker_left")
        if fields:
            settings.save(update_fields=fields)


class Migration(migrations.Migration):
    dependencies = [
        ("back", "0005_website_settings_bookmaker_placements"),
    ]

    operations = [
        migrations.RunPython(keep_existing_bookmaker_choices, migrations.RunPython.noop),
        migrations.RenameField(
            model_name="websitesettings",
            old_name="match_detail_bookmaker_left",
            new_name="match_bookmaker",
        ),
        migrations.RemoveField(
            model_name="websitesettings",
            name="match_detail_bookmaker_right",
        ),
        migrations.RenameField(
            model_name="websitesettings",
            old_name="prediction_bookmaker_left",
            new_name="prediction_bookmaker",
        ),
        migrations.RemoveField(
            model_name="websitesettings",
            name="prediction_bookmaker_right",
        ),
    ]
