import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("game", "0025_predictioncoupon_rich_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="MatchManualReview",
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
                    "reason",
                    models.CharField(
                        choices=[
                            ("missing_score", "Нет итогового счёта"),
                            ("invalid_score", "Некорректный счёт"),
                            ("unknown_market", "Неизвестный рынок"),
                            ("settlement_error", "Ошибка расчёта"),
                        ],
                        db_index=True,
                        max_length=32,
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("open", "Открыта"),
                            ("resolved", "Решена"),
                            ("ignored", "Игнорировать"),
                        ],
                        db_index=True,
                        default="open",
                        max_length=16,
                    ),
                ),
                ("details", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("resolved_at", models.DateTimeField(blank=True, null=True)),
                (
                    "match",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="manual_reviews",
                        to="game.match",
                    ),
                ),
            ],
            options={
                "ordering": ("-created_at", "-id"),
                "indexes": [
                    models.Index(
                        fields=["status", "reason", "created_at"],
                        name="match_review_status_idx",
                    ),
                    models.Index(
                        fields=["match", "status"],
                        name="match_review_match_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        condition=models.Q(("status", "open")),
                        fields=("match", "reason"),
                        name="unique_open_match_review_reason",
                    ),
                ],
            },
        ),
    ]
