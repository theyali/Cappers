from django.db import migrations, models
import django.db.models.deletion


def move_reactions_to_predictions(apps, schema_editor):
    PredictionItem = apps.get_model("game", "Prediction")
    PredictionLike = apps.get_model("front", "PredictionLike")
    PredictionFavorite = apps.get_model("front", "PredictionFavorite")

    coupon_by_item = dict(PredictionItem.objects.values_list("id", "coupon_id"))

    for model in (PredictionLike, PredictionFavorite):
        for reaction in model.objects.all().iterator():
            reaction.prediction_coupon_id = coupon_by_item.get(reaction.prediction_id)
            reaction.save(update_fields=["prediction_coupon"])

        seen = set()
        duplicate_ids = []
        for reaction in model.objects.exclude(prediction_coupon_id=None).order_by("id").iterator():
            key = (reaction.prediction_coupon_id, reaction.user_id)
            if key in seen:
                duplicate_ids.append(reaction.id)
            else:
                seen.add(key)
        if duplicate_ids:
            model.objects.filter(id__in=duplicate_ids).delete()


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("game", "0015_predictioncoupon_confidence"),
        ("front", "0004_remove_websitesettings"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="predictionlike",
            name="unique_prediction_like",
        ),
        migrations.RemoveIndex(
            model_name="predictionlike",
            name="pred_like_pred_created_idx",
        ),
        migrations.RemoveConstraint(
            model_name="predictionfavorite",
            name="unique_prediction_favorite",
        ),
        migrations.AddField(
            model_name="predictionlike",
            name="prediction_coupon",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="legacy_likes",
                to="game.predictioncoupon",
                verbose_name="Прогноз",
            ),
        ),
        migrations.AddField(
            model_name="predictionfavorite",
            name="prediction_coupon",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="legacy_favorites",
                to="game.predictioncoupon",
                verbose_name="Прогноз",
            ),
        ),
        migrations.RunPython(move_reactions_to_predictions, noop_reverse),
        migrations.RemoveField(
            model_name="predictionlike",
            name="prediction",
        ),
        migrations.RemoveField(
            model_name="predictionfavorite",
            name="prediction",
        ),
        migrations.RenameField(
            model_name="predictionlike",
            old_name="prediction_coupon",
            new_name="prediction",
        ),
        migrations.RenameField(
            model_name="predictionfavorite",
            old_name="prediction_coupon",
            new_name="prediction",
        ),
        migrations.AlterField(
            model_name="predictionlike",
            name="prediction",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="likes",
                to="game.predictioncoupon",
                verbose_name="Прогноз",
            ),
        ),
        migrations.AlterField(
            model_name="predictionfavorite",
            name="prediction",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="favorites",
                to="game.predictioncoupon",
                verbose_name="Прогноз",
            ),
        ),
        migrations.AddConstraint(
            model_name="predictionlike",
            constraint=models.UniqueConstraint(
                fields=("prediction", "user"),
                name="unique_prediction_like",
            ),
        ),
        migrations.AddIndex(
            model_name="predictionlike",
            index=models.Index(
                fields=["prediction", "created_at"],
                name="pred_like_pred_created_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="predictionfavorite",
            constraint=models.UniqueConstraint(
                fields=("prediction", "user"),
                name="unique_prediction_favorite",
            ),
        ),
    ]
