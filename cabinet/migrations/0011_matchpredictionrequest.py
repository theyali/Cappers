from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("game", "0017_match_provider_predictions_and_more"),
        ("cabinet", "0010_capperreferralvisit"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="MatchPredictionRequest",
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
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Запрошен")),
                (
                    "match",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="prediction_requests",
                        to="game.match",
                        verbose_name="Матч",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="match_prediction_requests",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Пользователь",
                    ),
                ),
            ],
            options={
                "verbose_name": "Запрос прогноза на матч",
                "verbose_name_plural": "Запросы прогнозов на матчи",
                "ordering": ("-created_at", "-id"),
                "indexes": [
                    models.Index(fields=["match", "created_at"], name="matchreq_match_created_idx"),
                    models.Index(fields=["user", "created_at"], name="matchreq_user_created_idx"),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("user", "match"),
                        name="unique_match_prediction_request",
                    )
                ],
            },
        ),
    ]
