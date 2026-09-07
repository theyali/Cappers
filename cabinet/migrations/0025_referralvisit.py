from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def copy_capper_referral_visits(apps, schema_editor):
    CapperReferralVisit = apps.get_model("cabinet", "CapperReferralVisit")
    ReferralVisit = apps.get_model("cabinet", "ReferralVisit")

    items = []
    for old in CapperReferralVisit.objects.all().iterator():
        items.append(
            ReferralVisit(
                referrer_id=old.analyst_id,
                visitor_id=old.visitor_id,
                session_key=old.session_key,
                visits_count=old.visits_count,
                first_seen_at=old.first_seen_at,
                last_seen_at=old.last_seen_at,
                registered_at=(old.subscribed_at or old.first_seen_at) if old.visitor_id else None,
                subscribed_at=old.subscribed_at,
            )
        )
        if len(items) >= 500:
            ReferralVisit.objects.bulk_create(items)
            items = []
    if items:
        ReferralVisit.objects.bulk_create(items)


class Migration(migrations.Migration):
    dependencies = [
        ("cabinet", "0024_user_referral_code"),
    ]

    operations = [
        migrations.CreateModel(
            name="ReferralVisit",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("session_key", models.CharField(max_length=40, verbose_name="Сессия")),
                ("visits_count", models.PositiveIntegerField(default=1, verbose_name="Переходы")),
                ("first_seen_at", models.DateTimeField(auto_now_add=True, verbose_name="Первый переход")),
                ("last_seen_at", models.DateTimeField(auto_now=True, verbose_name="Последний переход")),
                ("registered_at", models.DateTimeField(blank=True, null=True, verbose_name="Зарегистрировался")),
                ("subscribed_at", models.DateTimeField(blank=True, null=True, verbose_name="Подписался")),
                (
                    "referrer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="referral_visits",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Реферер",
                    ),
                ),
                (
                    "visitor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="referral_clicks",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Пользователь",
                    ),
                ),
            ],
            options={
                "verbose_name": "Переход по реферальной ссылке",
                "verbose_name_plural": "Переходы по реферальным ссылкам",
                "ordering": ("-last_seen_at", "-id"),
                "indexes": [
                    models.Index(fields=["referrer", "first_seen_at"], name="refvisit_ref_seen_idx"),
                    models.Index(fields=["referrer", "registered_at"], name="refvisit_ref_reg_idx"),
                    models.Index(fields=["referrer", "subscribed_at"], name="refvisit_ref_sub_idx"),
                    models.Index(fields=["visitor", "referrer"], name="refvisit_visitor_ref_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(fields=("referrer", "session_key"), name="unique_referral_session")
                ],
            },
        ),
        migrations.RunPython(copy_capper_referral_visits, migrations.RunPython.noop),
        migrations.DeleteModel(name="CapperReferralVisit"),
    ]
