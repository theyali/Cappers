from django.db import migrations, models


def copy_confidence_to_prediction(apps, schema_editor):
    PredictionCoupon = apps.get_model("game", "PredictionCoupon")
    PredictionItem = apps.get_model("game", "Prediction")

    first_confidence_by_coupon = {}
    rows = PredictionItem.objects.order_by("coupon_id", "id").values("coupon_id", "confidence")
    for row in rows.iterator():
        first_confidence_by_coupon.setdefault(row["coupon_id"], row["confidence"])

    for coupon in PredictionCoupon.objects.all().iterator():
        coupon.confidence = first_confidence_by_coupon.get(coupon.id, 50)
        coupon.save(update_fields=["confidence"])


class Migration(migrations.Migration):
    dependencies = [
        ("game", "0014_prediction_confidence_remove_comment"),
    ]

    operations = [
        migrations.AddField(
            model_name="predictioncoupon",
            name="confidence",
            field=models.PositiveSmallIntegerField(default=50, verbose_name="Уверенность"),
        ),
        migrations.RunPython(copy_confidence_to_prediction, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="prediction",
            name="confidence",
        ),
        migrations.AlterModelOptions(
            name="predictioncoupon",
            options={"ordering": ["-created_at"], "verbose_name": "Прогноз", "verbose_name_plural": "Прогнозы"},
        ),
        migrations.AlterModelOptions(
            name="prediction",
            options={"ordering": ["coupon_id", "id"], "verbose_name": "Позиция прогноза", "verbose_name_plural": "Позиции прогноза"},
        ),
    ]
