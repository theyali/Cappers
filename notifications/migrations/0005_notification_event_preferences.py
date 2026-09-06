from django.db import migrations, models


def disable_legacy_defaults(apps, schema_editor):
    NotificationPreference = apps.get_model("notifications", "NotificationPreference")
    NotificationPreference.objects.update(
        favorite_settled=False,
        match_reminder=False,
        achievement=False,
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0004_matchwatch_event_state"),
    ]

    operations = [
        migrations.AddField(
            model_name="notificationpreference",
            name="copybetting",
            field=models.BooleanField(default=True, verbose_name="Копибеттинг моих прогнозов"),
        ),
        migrations.AddField(
            model_name="notificationpreference",
            name="new_follower",
            field=models.BooleanField(default=True, verbose_name="Новые подписчики"),
        ),
        migrations.AddField(
            model_name="notificationpreference",
            name="own_coupon_settled",
            field=models.BooleanField(default=True, verbose_name="Расчёт моих купонов"),
        ),
        migrations.AddField(
            model_name="notificationpreference",
            name="paid_subscription",
            field=models.BooleanField(default=True, verbose_name="Покупка платной подписки"),
        ),
        migrations.AddField(
            model_name="notificationpreference",
            name="prediction_favorite",
            field=models.BooleanField(default=True, verbose_name="Сохранения моих прогнозов"),
        ),
        migrations.AddField(
            model_name="notificationpreference",
            name="prediction_like",
            field=models.BooleanField(default=True, verbose_name="Лайки моих прогнозов"),
        ),
        migrations.AddField(
            model_name="notificationpreference",
            name="requested_match_prediction",
            field=models.BooleanField(default=True, verbose_name="Прогнозы по запросу"),
        ),
        migrations.AddField(
            model_name="notificationpreference",
            name="tournament_finished",
            field=models.BooleanField(default=True, verbose_name="Завершение турнира"),
        ),
        migrations.AddField(
            model_name="notificationpreference",
            name="tournament_started",
            field=models.BooleanField(default=True, verbose_name="Старт турнира"),
        ),
        migrations.AlterField(
            model_name="notificationpreference",
            name="achievement",
            field=models.BooleanField(default=False, verbose_name="Достижения капперов"),
        ),
        migrations.AlterField(
            model_name="notificationpreference",
            name="favorite_settled",
            field=models.BooleanField(default=False, verbose_name="Расчёт избранных прогнозов"),
        ),
        migrations.AlterField(
            model_name="notificationpreference",
            name="match_reminder",
            field=models.BooleanField(default=False, verbose_name="Напоминания о матчах"),
        ),
        migrations.AlterField(
            model_name="notification",
            name="kind",
            field=models.CharField(
                choices=[
                    ("prediction_like", "Лайк прогноза"),
                    ("prediction_favorite", "Сохранение прогноза"),
                    ("copybetting", "Копибеттинг"),
                    ("new_follower", "Новый подписчик"),
                    ("paid_subscription", "Платная подписка"),
                    ("new_prediction", "Новый прогноз"),
                    ("requested_match_prediction", "Прогноз по запросу"),
                    ("match_prediction", "Прогноз на отслеживаемый матч"),
                    ("tournament_started", "Турнир начался"),
                    ("tournament_finished", "Турнир завершён"),
                    ("own_coupon_settled", "Мой купон рассчитан"),
                    ("favorite_settled", "Избранный прогноз рассчитан"),
                    ("match_reminder", "Скоро матч"),
                    ("achievement", "Достижение каппера"),
                ],
                db_index=True,
                max_length=32,
                verbose_name="Тип",
            ),
        ),
        migrations.RunPython(disable_legacy_defaults, noop_reverse),
    ]
