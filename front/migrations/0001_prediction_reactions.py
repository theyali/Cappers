from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("game", "0011_matchodds_btts_all_matchodds_double_chance_all_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="PredictionFavorite",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("prediction", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="favorites", to="game.prediction", verbose_name="Прогноз")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="prediction_favorites", to=settings.AUTH_USER_MODEL, verbose_name="Пользователь")),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.CreateModel(
            name="PredictionLike",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("prediction", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="likes", to="game.prediction", verbose_name="Прогноз")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="prediction_likes", to=settings.AUTH_USER_MODEL, verbose_name="Пользователь")),
            ],
            options={"ordering": ("-created_at",)},
        ),
        migrations.AddConstraint(
            model_name="predictionfavorite",
            constraint=models.UniqueConstraint(fields=("prediction", "user"), name="unique_prediction_favorite"),
        ),
        migrations.AddIndex(
            model_name="predictionfavorite",
            index=models.Index(fields=["user", "created_at"], name="pred_fav_user_created_idx"),
        ),
        migrations.AddConstraint(
            model_name="predictionlike",
            constraint=models.UniqueConstraint(fields=("prediction", "user"), name="unique_prediction_like"),
        ),
        migrations.AddIndex(
            model_name="predictionlike",
            index=models.Index(fields=["prediction", "created_at"], name="pred_like_pred_created_idx"),
        ),
        migrations.AddIndex(
            model_name="predictionlike",
            index=models.Index(fields=["user", "created_at"], name="pred_like_user_created_idx"),
        ),
    ]
