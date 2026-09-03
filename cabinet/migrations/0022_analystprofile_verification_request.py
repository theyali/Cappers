from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cabinet", "0021_paid_prediction_plans"),
    ]

    operations = [
        migrations.AddField(
            model_name="analystprofile",
            name="verification_requested_at",
            field=models.DateTimeField(
                blank=True,
                db_index=True,
                null=True,
                verbose_name="Запрос проверки отправлен",
            ),
        ),
    ]
