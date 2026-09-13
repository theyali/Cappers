from django.db import migrations, models


OLD_REWARD_TYPE = "virtual_balance"
NEW_REWARD_TYPE = "coins"


REWARD_CHOICES = [
    ("coins", "Коины"),
    ("vip_days", "VIP на несколько дней"),
    ("free_predictions", "Бесплатные прогнозы"),
    ("promo_code", "Промокод"),
    ("rating_boost", "Буст рейтинга"),
    ("extra_spin", "Дополнительная попытка"),
    ("nothing", "Пустой сектор"),
]


def rename_virtual_balance_to_coins(apps, schema_editor):
    RoulettePrize = apps.get_model("cabinet", "RoulettePrize")
    RouletteSpin = apps.get_model("cabinet", "RouletteSpin")
    RoulettePrize.objects.filter(reward_type=OLD_REWARD_TYPE).update(reward_type=NEW_REWARD_TYPE)
    RouletteSpin.objects.filter(reward_type=OLD_REWARD_TYPE).update(reward_type=NEW_REWARD_TYPE)


def rename_coins_to_virtual_balance(apps, schema_editor):
    RoulettePrize = apps.get_model("cabinet", "RoulettePrize")
    RouletteSpin = apps.get_model("cabinet", "RouletteSpin")
    RoulettePrize.objects.filter(reward_type=NEW_REWARD_TYPE).update(reward_type=OLD_REWARD_TYPE)
    RouletteSpin.objects.filter(reward_type=NEW_REWARD_TYPE).update(reward_type=OLD_REWARD_TYPE)


class Migration(migrations.Migration):

    dependencies = [
        ("cabinet", "0031_userroulettestate_available_spins_nonneg"),
    ]

    operations = [
        migrations.RunPython(
            rename_virtual_balance_to_coins,
            rename_coins_to_virtual_balance,
        ),
        migrations.AlterField(
            model_name="rouletteprize",
            name="reward_type",
            field=models.CharField(
                choices=REWARD_CHOICES,
                db_index=True,
                max_length=32,
                verbose_name="Тип награды",
            ),
        ),
        migrations.AlterField(
            model_name="roulettespin",
            name="reward_type",
            field=models.CharField(
                choices=REWARD_CHOICES,
                max_length=32,
                verbose_name="Тип награды на момент выигрыша",
            ),
        ),
    ]
