from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("cabinet", "0019_analystprofile_is_recommended"),
    ]

    operations = [
        migrations.AddField(
            model_name="analystprofile",
            name="paid_predictions_enabled",
            field=models.BooleanField(
                db_index=True,
                default=False,
                verbose_name="Платные прогнозы",
            ),
        ),
        migrations.AddField(
            model_name="analystprofile",
            name="paid_predictions_price",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                max_digits=10,
                verbose_name="Стоимость подписки в месяц",
            ),
        ),
        migrations.CreateModel(
            name="AnalystPaidSubscription",
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
                    "price",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=10,
                        verbose_name="Стоимость на момент подписки",
                    ),
                ),
                (
                    "starts_at",
                    models.DateTimeField(
                        default=django.utils.timezone.now,
                        verbose_name="Начало подписки",
                    ),
                ),
                ("expires_at", models.DateTimeField(verbose_name="Действует до")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создана")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлена")),
                (
                    "analyst",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="paid_prediction_subscribers",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Аналитик",
                    ),
                ),
                (
                    "subscriber",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="paid_prediction_subscriptions",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Подписчик",
                    ),
                ),
            ],
            options={
                "verbose_name": "Платная подписка на прогнозы",
                "verbose_name_plural": "Платные подписки на прогнозы",
                "ordering": ("-expires_at", "-id"),
            },
        ),
        migrations.AddConstraint(
            model_name="analystpaidsubscription",
            constraint=models.UniqueConstraint(
                fields=("subscriber", "analyst"),
                name="unique_paid_prediction_subscription",
            ),
        ),
        migrations.AddIndex(
            model_name="analystpaidsubscription",
            index=models.Index(
                fields=("subscriber", "expires_at"),
                name="paid_sub_subscriber_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="analystpaidsubscription",
            index=models.Index(
                fields=("analyst", "expires_at"),
                name="paid_sub_analyst_idx",
            ),
        ),
    ]
