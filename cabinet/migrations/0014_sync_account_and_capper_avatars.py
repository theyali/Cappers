from django.db import migrations


def sync_avatars(apps, schema_editor):
    User = apps.get_model("cabinet", "User")
    AnalystProfile = apps.get_model("cabinet", "AnalystProfile")

    for profile in AnalystProfile.objects.select_related("user").iterator():
        user = profile.user
        user_avatar = getattr(user.avatar, "name", "") or ""
        profile_avatar = getattr(profile.avatar, "name", "") or ""

        if user_avatar:
            if profile_avatar != user_avatar:
                AnalystProfile.objects.filter(pk=profile.pk).update(avatar=user_avatar)
        elif profile_avatar:
            User.objects.filter(pk=user.pk).update(avatar=profile_avatar)


class Migration(migrations.Migration):
    dependencies = [
        ("cabinet", "0013_optional_telegram_profile_fields"),
    ]

    operations = [
        migrations.RunPython(sync_avatars, migrations.RunPython.noop),
    ]
