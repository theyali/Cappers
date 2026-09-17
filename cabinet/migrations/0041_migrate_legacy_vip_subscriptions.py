from datetime import datetime, timedelta, timezone as datetime_timezone

from django.db import migrations, models


LEGACY_SOURCE = "legacy_admin"
LEGACY_ENDS_AT = datetime(2099, 12, 31, 23, 59, 59, tzinfo=datetime_timezone.utc)


def migrate_legacy_vip_subscriptions(apps, schema_editor):
    AnalystProfile = apps.get_model("cabinet", "AnalystProfile")
    UserVipSubscription = apps.get_model("cabinet", "UserVipSubscription")

    profiles = (
        AnalystProfile.objects.filter(is_vip=True)
        .select_related("user")
        .iterator()
    )

    for profile in profiles:
        starts_at = (
            profile.vip_activated_at
            or profile.updated_at
            or profile.user.date_joined
        )
        if starts_at is None:
            continue

        ends_at = max(LEGACY_ENDS_AT, starts_at + timedelta(days=1))
        duration_days = max(1, (ends_at - starts_at).days)

        UserVipSubscription.objects.get_or_create(
            user_id=profile.user_id,
            source=LEGACY_SOURCE,
            defaults={
                "plan_id": None,
                "starts_at": starts_at,
                "ends_at": ends_at,
                "duration_days": duration_days,
                "is_active": True,
            },
        )


def reverse_legacy_vip_subscriptions(apps, schema_editor):
    UserVipSubscription = apps.get_model("cabinet", "UserVipSubscription")
    UserVipSubscription.objects.filter(source=LEGACY_SOURCE).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("cabinet", "0040_vip_plan_and_subscription"),
    ]

    operations = [
        migrations.AlterField(
            model_name="uservipsubscription",
            name="source",
            field=models.CharField(
                choices=[
                    ("purchase", "Покупка"),
                    ("admin", "Администратор"),
                    ("roulette", "Рулетка"),
                    ("bonus", "Бонус"),
                    ("legacy_admin", "Перенос старого VIP"),
                ],
                default="purchase",
                max_length=16,
                verbose_name="Источник",
            ),
        ),
        migrations.RunPython(
            migrate_legacy_vip_subscriptions,
            reverse_legacy_vip_subscriptions,
        ),
    ]
