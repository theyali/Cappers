import secrets

import cabinet.models
from django.db import migrations, models


REFERRAL_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _new_code(existing: set[str]) -> str:
    while True:
        code = "".join(secrets.choice(REFERRAL_CODE_ALPHABET) for _ in range(8))
        if code not in existing:
            return code


def backfill_referral_codes(apps, schema_editor):
    AnalystProfile = apps.get_model("cabinet", "AnalystProfile")
    existing = set(
        AnalystProfile.objects.exclude(referral_code__isnull=True)
        .exclude(referral_code="")
        .values_list("referral_code", flat=True)
    )
    for profile in AnalystProfile.objects.filter(referral_code__isnull=True).iterator():
        code = _new_code(existing)
        AnalystProfile.objects.filter(pk=profile.pk).update(referral_code=code)
        existing.add(code)


class Migration(migrations.Migration):
    dependencies = [
        ("cabinet", "0011_matchpredictionrequest"),
    ]

    operations = [
        migrations.AddField(
            model_name="analystprofile",
            name="referral_code",
            field=models.CharField(
                blank=True,
                max_length=8,
                null=True,
                unique=True,
                verbose_name="Реферальный код",
            ),
        ),
        migrations.RunPython(backfill_referral_codes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="analystprofile",
            name="referral_code",
            field=models.CharField(
                default=cabinet.models.generate_referral_code,
                editable=False,
                max_length=8,
                unique=True,
                verbose_name="Реферальный код",
            ),
        ),
    ]
