from django.db import migrations


def move_profile_avatars_to_user(apps, schema_editor):
    AnalystProfile = apps.get_model("cabinet", "AnalystProfile")
    User = apps.get_model("cabinet", "User")

    for profile in AnalystProfile.objects.select_related("user").iterator():
        profile_avatar = getattr(profile.avatar, "name", "") or ""
        if not profile_avatar:
            continue

        user_avatar = getattr(profile.user.avatar, "name", "") or ""
        if user_avatar:
            continue

        User.objects.filter(pk=profile.user_id).update(avatar=profile_avatar)


class Migration(migrations.Migration):
    dependencies = [
        ("cabinet", "0050_user_sport_and_league_preferences"),
    ]

    operations = [
        migrations.RunPython(
            move_profile_avatars_to_user,
            migrations.RunPython.noop,
        ),
        migrations.RemoveField(
            model_name="analystprofile",
            name="avatar",
        ),
    ]
