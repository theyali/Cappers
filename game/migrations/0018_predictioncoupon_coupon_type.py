from django.db import migrations, models
from django.db.models import Count


def backfill_coupon_types(apps, schema_editor):
    Prediction = apps.get_model("game", "Prediction")
    PredictionCoupon = apps.get_model("game", "PredictionCoupon")

    express_coupon_ids = (
        Prediction.objects.values("coupon_id")
        .annotate(positions_count=Count("id"))
        .filter(positions_count__gt=1)
        .values_list("coupon_id", flat=True)
    )
    PredictionCoupon.objects.filter(pk__in=express_coupon_ids).update(
        coupon_type="express"
    )


def reset_coupon_types(apps, schema_editor):
    PredictionCoupon = apps.get_model("game", "PredictionCoupon")
    PredictionCoupon.objects.all().update(coupon_type="single")


class Migration(migrations.Migration):
    dependencies = [
        ("game", "0017_match_provider_predictions_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="predictioncoupon",
            name="coupon_type",
            field=models.CharField(
                choices=[("single", "Одиночный"), ("express", "Экспресс")],
                db_index=True,
                default="single",
                max_length=16,
                verbose_name="Тип прогноза",
            ),
        ),
        migrations.RunPython(backfill_coupon_types, reset_coupon_types),
    ]
