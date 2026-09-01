from django.db import migrations
from django.db.models import F


def remove_self_prediction_reactions(apps, schema_editor):
    PredictionLike = apps.get_model("front", "PredictionLike")
    PredictionFavorite = apps.get_model("front", "PredictionFavorite")

    PredictionLike.objects.filter(user_id=F("prediction__author_id")).delete()
    PredictionFavorite.objects.filter(user_id=F("prediction__author_id")).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("front", "0005_reactions_to_predictioncoupon"),
    ]

    operations = [
        migrations.RunPython(remove_self_prediction_reactions, migrations.RunPython.noop),
    ]
