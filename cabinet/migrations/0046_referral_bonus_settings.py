from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cabinet", "0045_bonus_event"),
    ]

    operations = [
        migrations.CreateModel(
            name="ReferralBonusSettings",
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
                    "registration_reward_coins",
                    models.PositiveIntegerField(
                        default=0,
                        verbose_name="Коины за регистрацию",
                    ),
                ),
                (
                    "registration_reward_xp",
                    models.PositiveIntegerField(
                        default=0,
                        verbose_name="XP за регистрацию",
                    ),
                ),
                (
                    "first_topup_reward_coins",
                    models.PositiveIntegerField(
                        default=0,
                        verbose_name="Коины за первое пополнение",
                    ),
                ),
                (
                    "first_subscription_reward_coins",
                    models.PositiveIntegerField(
                        default=0,
                        verbose_name="Коины за первую подписку",
                    ),
                ),
                (
                    "max_visible_reward_text",
                    models.CharField(
                        default="До 1000 монет",
                        max_length=120,
                        verbose_name="Текст максимальной награды",
                    ),
                ),
                (
                    "is_enabled",
                    models.BooleanField(
                        default=True,
                        verbose_name="Реферальные бонусы включены",
                    ),
                ),
            ],
            options={
                "verbose_name": "Настройки реферальных бонусов",
                "verbose_name_plural": "Настройки реферальных бонусов",
            },
        ),
    ]
