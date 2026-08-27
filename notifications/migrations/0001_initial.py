from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("cabinet", "0007_user_avatar"),
        ("game", "0016_alter_prediction_coupon_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="AchievementState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("unlocked_keys", models.JSONField(blank=True, default=list, verbose_name="Полученные достижения")),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="notification_achievement_state", to=settings.AUTH_USER_MODEL, verbose_name="Каппер")),
            ],
            options={
                "verbose_name": "Состояние достижений для уведомлений",
                "verbose_name_plural": "Состояния достижений для уведомлений",
            },
        ),
        migrations.CreateModel(
            name="NotificationPreference",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("in_app_enabled", models.BooleanField(default=True, verbose_name="На сайте")),
                ("email_enabled", models.BooleanField(default=False, verbose_name="Email")),
                ("telegram_enabled", models.BooleanField(default=False, verbose_name="Telegram")),
                ("telegram_chat_id", models.CharField(blank=True, max_length=80, verbose_name="Telegram chat id")),
                ("new_prediction", models.BooleanField(default=True, verbose_name="Новые прогнозы капперов")),
                ("favorite_settled", models.BooleanField(default=True, verbose_name="Расчёт избранных прогнозов")),
                ("match_reminder", models.BooleanField(default=True, verbose_name="Напоминания о матчах")),
                ("achievement", models.BooleanField(default=True, verbose_name="Достижения капперов")),
                ("match_prediction", models.BooleanField(default=True, verbose_name="Прогнозы на отслеживаемые матчи")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="notification_preferences", to=settings.AUTH_USER_MODEL, verbose_name="Пользователь")),
            ],
            options={
                "verbose_name": "Настройки уведомлений",
                "verbose_name_plural": "Настройки уведомлений",
            },
        ),
        migrations.CreateModel(
            name="MatchWatch",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("match", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="notification_watchers", to="game.match", verbose_name="Матч")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="notification_match_watches", to=settings.AUTH_USER_MODEL, verbose_name="Пользователь")),
            ],
            options={
                "verbose_name": "Отслеживаемый матч",
                "verbose_name_plural": "Отслеживаемые матчи",
                "ordering": ("-created_at",),
                "indexes": [
                    models.Index(fields=["match", "created_at"], name="notif_watch_match_idx"),
                    models.Index(fields=["user", "created_at"], name="notif_watch_user_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(fields=("user", "match"), name="unique_notification_match_watch"),
                ],
            },
        ),
        migrations.CreateModel(
            name="CouponEventState",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("published_dispatched_at", models.DateTimeField(blank=True, null=True)),
                ("settled_state", models.CharField(blank=True, max_length=16)),
                ("settled_dispatched_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("coupon", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="notification_event_state", to="game.predictioncoupon", verbose_name="Прогноз")),
            ],
            options={
                "verbose_name": "Состояние событий прогноза",
                "verbose_name_plural": "Состояния событий прогнозов",
            },
        ),
        migrations.CreateModel(
            name="Notification",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("new_prediction", "Новый прогноз"), ("favorite_settled", "Избранный прогноз рассчитан"), ("match_reminder", "Скоро матч"), ("achievement", "Достижение каппера"), ("match_prediction", "Прогноз на отслеживаемый матч")], db_index=True, max_length=32, verbose_name="Тип")),
                ("title", models.CharField(max_length=180, verbose_name="Заголовок")),
                ("message", models.TextField(blank=True, max_length=1000, verbose_name="Текст")),
                ("url", models.CharField(blank=True, max_length=500, verbose_name="Ссылка")),
                ("event_key", models.CharField(max_length=255, unique=True, verbose_name="Ключ события")),
                ("meta", models.JSONField(blank=True, default=dict, verbose_name="Данные")),
                ("show_in_app", models.BooleanField(db_index=True, default=True, verbose_name="Показывать на сайте")),
                ("is_read", models.BooleanField(db_index=True, default=False, verbose_name="Прочитано")),
                ("read_at", models.DateTimeField(blank=True, null=True, verbose_name="Прочитано в")),
                ("email_processed_at", models.DateTimeField(blank=True, null=True)),
                ("email_sent_at", models.DateTimeField(blank=True, null=True)),
                ("telegram_processed_at", models.DateTimeField(blank=True, null=True)),
                ("telegram_sent_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Создано")),
                ("actor", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="notification_actions", to=settings.AUTH_USER_MODEL, verbose_name="Инициатор")),
                ("recipient", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="notifications", to=settings.AUTH_USER_MODEL, verbose_name="Получатель")),
            ],
            options={
                "verbose_name": "Уведомление",
                "verbose_name_plural": "Уведомления",
                "ordering": ("-created_at", "-id"),
                "indexes": [
                    models.Index(fields=["recipient", "show_in_app", "is_read", "created_at"], name="notif_recipient_state_idx"),
                    models.Index(fields=["kind", "created_at"], name="notif_kind_created_idx"),
                ],
            },
        ),
    ]
