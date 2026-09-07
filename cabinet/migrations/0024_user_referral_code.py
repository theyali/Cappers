import secrets

import cabinet.models
from django.db import migrations, models


REFERRAL_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _new_code(existing: set[str]) -> str:
    while True:
        code = "".join(secrets.choice(REFERRAL_CODE_ALPHABET) for _ in range(8))
        if code not in existing:
            return code


def move_referral_codes_to_user(apps, schema_editor):
    User = apps.get_model("cabinet", "User")
    AnalystProfile = apps.get_model("cabinet", "AnalystProfile")

    existing = set(
        User.objects.exclude(referral_code__isnull=True)
        .exclude(referral_code="")
        .values_list("referral_code", flat=True)
    )

    profiles_by_user_id = {
        profile.user_id: profile.referral_code
        for profile in AnalystProfile.objects.exclude(referral_code__isnull=True)
        .exclude(referral_code="")
        .iterator()
    }

    for user in User.objects.only("id", "referral_code").iterator():
        if user.referral_code:
            existing.add(user.referral_code)
            continue

        profile_code = profiles_by_user_id.get(user.id)
        if profile_code and profile_code not in existing:
            code = profile_code
        else:
            code = _new_code(existing)

        User.objects.filter(pk=user.pk).update(referral_code=code)
        existing.add(code)


class Migration(migrations.Migration):
    dependencies = [
        ("cabinet", "0023_analystprofile_trust_index_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="referral_code",
            field=models.CharField(
                blank=True,
                editable=False,
                max_length=8,
                null=True,
                unique=True,
                verbose_name="Реферальный код",
            ),
        ),
        migrations.RunPython(move_referral_codes_to_user, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="user",
            name="referral_code",
            field=models.CharField(
                default=cabinet.models.generate_referral_code,
                editable=False,
                max_length=8,
                unique=True,
                verbose_name="Реферальный код",
            ),
        ),
        migrations.RemoveField(
            model_name="analystprofile",
            name="referral_code",
        ),
    ]
