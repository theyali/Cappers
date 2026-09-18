from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0005_notification_event_preferences"),
    ]

    operations = [
        migrations.AddField(
            model_name="notificationpreference",
            name="bonus_daily_task",
            field=models.BooleanField(
                default=True,
                verbose_name="Награды за ежедневные задания",
            ),
        ),
        migrations.AddField(
            model_name="notificationpreference",
            name="bonus_streak",
            field=models.BooleanField(
                default=True,
                verbose_name="Награды за серию дней",
            ),
        ),
        migrations.AddField(
            model_name="notificationpreference",
            name="bonus_level",
            field=models.BooleanField(
                default=True,
                verbose_name="Новый уровень",
            ),
        ),
        migrations.AddField(
            model_name="notificationpreference",
            name="bonus_roulette",
            field=models.BooleanField(
                default=False,
                verbose_name="Призы рулетки",
            ),
        ),
        migrations.AddField(
            model_name="notificationpreference",
            name="bonus_referral",
            field=models.BooleanField(
                default=True,
                verbose_name="Реферальные бонусы",
            ),
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
                    ("bonus_daily_task", "Награда за ежедневное задание"),
                    ("bonus_streak", "Награда за серию дней"),
                    ("bonus_level", "Новый уровень"),
                    ("bonus_roulette", "Приз рулетки"),
                    ("bonus_referral", "Реферальный бонус"),
                ],
                db_index=True,
                max_length=32,
                verbose_name="Тип",
            ),
        ),
    ]
