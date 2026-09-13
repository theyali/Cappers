from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cabinet", "0032_roulette_reward_type_coins"),
    ]

    operations = [
        migrations.AlterField(
            model_name="rouletteprize",
            name="reward_value",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                help_text="Количество коинов, дней, прогнозов, попыток или размер буста — зависит от типа награды.",
                max_digits=12,
                verbose_name="Величина награды",
            ),
        ),
    ]
