from django.db import migrations, models
from django.db.models import F


def seed_existing_vip_dates(apps, schema_editor):
    AnalystProfile = apps.get_model("cabinet", "AnalystProfile")
    AnalystProfile.objects.filter(
        is_vip=True,
        vip_activated_at__isnull=True,
    ).update(vip_activated_at=F("updated_at"))


def clear_seeded_vip_dates(apps, schema_editor):
    AnalystProfile = apps.get_model("cabinet", "AnalystProfile")
    AnalystProfile.objects.update(vip_activated_at=None)


class Migration(migrations.Migration):
    dependencies = [
        ("cabinet", "0038_comment_query_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="analystprofile",
            name="vip_activated_at",
            field=models.DateTimeField(
                blank=True,
                db_index=True,
                null=True,
                verbose_name="VIP активирован",
            ),
        ),
        migrations.RunPython(seed_existing_vip_dates, clear_seeded_vip_dates),
    ]
