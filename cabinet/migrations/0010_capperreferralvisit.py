from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("cabinet", "0009_analystprofile_onboarding_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="CapperReferralVisit",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("session_key", models.CharField(max_length=40, verbose_name="Сессия")),
                ("visits_count", models.PositiveIntegerField(default=1, verbose_name="Переходы")),
                ("first_seen_at", models.DateTimeField(auto_now_add=True, verbose_name="Первый переход")),
                ("last_seen_at", models.DateTimeField(auto_now=True, verbose_name="Последний переход")),
                ("subscribed_at", models.DateTimeField(blank=True, null=True, verbose_name="Подписался")),
                (
                    "analyst",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="capper_referral_visits",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Каппер",
                    ),
                ),
                (
                    "visitor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="capper_referral_clicks",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Пользователь",
                    ),
                ),
            ],
            options={
                "verbose_name": "Переход по реферальной ссылке каппера",
                "verbose_name_plural": "Переходы по реферальным ссылкам капперов",
                "ordering": ("-last_seen_at", "-id"),
                "indexes": [
                    models.Index(fields=["analyst", "first_seen_at"], name="capref_analyst_seen_idx"),
                    models.Index(fields=["analyst", "subscribed_at"], name="capref_analyst_sub_idx"),
                    models.Index(fields=["visitor", "analyst"], name="capref_visitor_analyst_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("analyst", "session_key"),
                        name="unique_capper_referral_session",
                    )
                ],
            },
        ),
    ]
