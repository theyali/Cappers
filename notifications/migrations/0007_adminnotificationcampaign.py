from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("notifications", "0006_bonus_notification_preferences"),
        ("tournaments", "0002_alter_tournament_min_confidence"),
    ]

    operations = [
        migrations.CreateModel(
            name="AdminNotificationCampaign",
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
                    "audience",
                    models.CharField(
                        choices=[
                            ("all_users", "Все пользователи"),
                            ("vip_users", "VIP-пользователи"),
                            ("readers", "Обычные пользователи"),
                            ("cappers", "Капперы"),
                            (
                                "readers_and_cappers",
                                "Пользователи и капперы",
                            ),
                            (
                                "tournament_winners",
                                "Победители турниров",
                            ),
                            (
                                "tournament_participants",
                                "Участники выбранного турнира",
                            ),
                            (
                                "inactive_users",
                                "Неактивные пользователи",
                            ),
                        ],
                        db_index=True,
                        max_length=32,
                        verbose_name="Аудитория",
                    ),
                ),
                (
                    "title",
                    models.CharField(
                        max_length=180,
                        verbose_name="Заголовок",
                    ),
                ),
                ("message", models.TextField(verbose_name="Текст")),
                (
                    "url",
                    models.CharField(
                        blank=True,
                        max_length=500,
                        verbose_name="Ссылка",
                    ),
                ),
                (
                    "image",
                    models.ImageField(
                        blank=True,
                        upload_to="notifications/campaigns/%Y/%m/",
                        verbose_name="Изображение",
                    ),
                ),
                (
                    "inactive_days",
                    models.PositiveIntegerField(
                        blank=True,
                        null=True,
                        verbose_name="Неактивен, дней",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        verbose_name="Создано",
                    ),
                ),
                (
                    "sent_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                        verbose_name="Отправлено",
                    ),
                ),
                (
                    "recipients_count",
                    models.PositiveIntegerField(
                        default=0,
                        verbose_name="Получателей",
                    ),
                ),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="created_notification_campaigns",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Создал",
                    ),
                ),
                (
                    "tournament",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="notification_campaigns",
                        to="tournaments.tournament",
                        verbose_name="Турнир",
                    ),
                ),
            ],
            options={
                "verbose_name": "Массовая рассылка уведомлений",
                "verbose_name_plural": "Массовые рассылки уведомлений",
                "ordering": ("-created_at", "-id"),
            },
        ),
    ]
