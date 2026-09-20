import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cabinet", "0049_capperarticle"),
        ("game", "0025_predictioncoupon_rich_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserSportPreference",
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
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "sport",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="user_preferences",
                        to="game.sport",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="sport_preferences",
                        to="cabinet.user",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["user", "sport"],
                        name="cab_user_sport_idx",
                    ),
                    models.Index(
                        fields=["sport"],
                        name="cab_sport_pref_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("user", "sport"),
                        name="unique_user_sport_preference",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="UserLeaguePreference",
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
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "league",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="user_preferences",
                        to="game.league",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="league_preferences",
                        to="cabinet.user",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["user", "league"],
                        name="cab_user_league_idx",
                    ),
                    models.Index(
                        fields=["league"],
                        name="cab_league_pref_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("user", "league"),
                        name="unique_user_league_preference",
                    ),
                ],
            },
        ),
    ]
