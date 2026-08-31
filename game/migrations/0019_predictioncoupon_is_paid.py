from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("game", "0018_predictioncoupon_coupon_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="predictioncoupon",
            name="is_paid",
            field=models.BooleanField(
                db_index=True,
                default=False,
                verbose_name="Платный прогноз",
            ),
        ),
        migrations.AddIndex(
            model_name="predictioncoupon",
            index=models.Index(
                fields=["published_status", "is_paid", "created_at"],
                name="coupon_public_paid_idx",
            ),
        ),
    ]
