from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cabinet", "0030_userrouletterewardstate"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="userroulettestate",
            constraint=models.CheckConstraint(
                condition=models.Q(available_spins__gte=0),
                name="roulette_state_available_spins_nonneg",
            ),
        ),
    ]
