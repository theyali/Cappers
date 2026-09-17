from django.conf import settings
import django.db.models.deletion
from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("cabinet", "0039_analystprofile_vip_activated_at"),
    ]

    operations = [
        migrations.CreateModel(
            name="VipPlan",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("title", models.CharField(max_length=120, verbose_name="Название")),
                ("duration_days", models.PositiveIntegerField(verbose_name="Срок, дней")),
                (
                    "price_coins",
                    models.PositiveIntegerField(default=0, verbose_name="Стоимость, коинов"),
                ),
                ("is_active", models.BooleanField(default=True, verbose_name="Активен")),
                ("order", models.PositiveIntegerField(default=0, verbose_name="Порядок")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создан")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлён")),
            ],
            options={
                "verbose_name": "VIP-тариф",
                "verbose_name_plural": "VIP-тарифы",
                "ordering": ("order", "duration_days", "id"),
            },
        ),
        migrations.CreateModel(
            name="UserVipSubscription",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "starts_at",
                    models.DateTimeField(default=django.utils.timezone.now, verbose_name="Начало VIP"),
                ),
                ("ends_at", models.DateTimeField(verbose_name="Окончание VIP")),
                ("duration_days", models.PositiveIntegerField(verbose_name="Срок, дней")),
                (
                    "source",
                    models.CharField(
                        choices=[
                            ("purchase", "Покупка"),
                            ("admin", "Администратор"),
                            ("roulette", "Рулетка"),
                            ("bonus", "Бонус"),
                        ],
                        default="purchase",
                        max_length=16,
                        verbose_name="Источник",
                    ),
                ),
                ("is_active", models.BooleanField(default=True, verbose_name="Активен")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создан")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлён")),
                (
                    "plan",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="subscriptions",
                        to="cabinet.vipplan",
                        verbose_name="VIP-тариф",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="vip_subscriptions",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Пользователь",
                    ),
                ),
            ],
            options={
                "verbose_name": "VIP-период пользователя",
                "verbose_name_plural": "VIP-периоды пользователей",
                "ordering": ("-ends_at", "-id"),
                "indexes": [
                    models.Index(
                        fields=["user", "starts_at", "ends_at"],
                        name="vip_sub_user_period_idx",
                    ),
                    models.Index(
                        fields=["user", "is_active", "ends_at"],
                        name="vip_sub_user_active_idx",
                    ),
                    models.Index(fields=["ends_at"], name="vip_sub_ends_idx"),
                ],
            },
        ),
    ]
