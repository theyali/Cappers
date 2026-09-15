from django.db import migrations, models
from django.db.models import Count
from django.utils import timezone


def backfill_metrics(apps, schema_editor):
    PredictionCoupon = apps.get_model("game", "PredictionCoupon")
    Prediction = apps.get_model("game", "Prediction")
    Match = apps.get_model("game", "Match")
    Comment = apps.get_model("cabinet", "Comment")
    PredictionLike = apps.get_model("front", "PredictionLike")
    PredictionFavorite = apps.get_model("front", "PredictionFavorite")
    PredictionMetrics = apps.get_model("front", "PredictionMetrics")
    MatchMetrics = apps.get_model("front", "MatchMetrics")
    MatchWatch = apps.get_model("notifications", "MatchWatch")
    ContentType = apps.get_model("contenttypes", "ContentType")

    now = timezone.now()
    prediction_content_type = ContentType.objects.filter(
        app_label="game",
        model="predictioncoupon",
    ).first()
    match_content_type = ContentType.objects.filter(
        app_label="game",
        model="match",
    ).first()

    like_counts = {
        row["prediction_id"]: row["total"]
        for row in PredictionLike.objects.values("prediction_id").annotate(total=Count("id"))
    }
    favorite_counts = {
        row["prediction_id"]: row["total"]
        for row in PredictionFavorite.objects.values("prediction_id").annotate(total=Count("id"))
    }
    prediction_comment_counts = {}
    if prediction_content_type is not None:
        prediction_comment_counts = {
            row["object_id"]: row["total"]
            for row in Comment.objects.filter(
                content_type_id=prediction_content_type.pk,
                status="published",
                parent_id__isnull=True,
            )
            .values("object_id")
            .annotate(total=Count("id"))
        }

    PredictionMetrics.objects.bulk_create(
        [
            PredictionMetrics(
                coupon_id=coupon_id,
                likes_count=like_counts.get(coupon_id, 0),
                comments_count=prediction_comment_counts.get(coupon_id, 0),
                favorites_count=favorite_counts.get(coupon_id, 0),
                views_count=0,
                shares_count=0,
                updated_at=now,
            )
            for coupon_id in PredictionCoupon.objects.values_list("id", flat=True).iterator()
        ],
        batch_size=1000,
        ignore_conflicts=True,
    )

    match_prediction_counts = {
        row["match_id"]: row["total"]
        for row in Prediction.objects.filter(
            coupon__published_status="published",
            coupon__audience="free",
        )
        .values("match_id")
        .annotate(total=Count("coupon_id", distinct=True))
    }
    match_favorite_counts = {
        row["match_id"]: row["total"]
        for row in MatchWatch.objects.values("match_id").annotate(total=Count("id"))
    }
    match_comment_counts = {}
    if match_content_type is not None:
        match_comment_counts = {
            row["object_id"]: row["total"]
            for row in Comment.objects.filter(
                content_type_id=match_content_type.pk,
                status="published",
                parent_id__isnull=True,
            )
            .values("object_id")
            .annotate(total=Count("id"))
        }

    match_rows = []
    for match_id in Match.objects.values_list("id", flat=True).iterator():
        predictions_count = match_prediction_counts.get(match_id, 0)
        comments_count = match_comment_counts.get(match_id, 0)
        favorites_count = match_favorite_counts.get(match_id, 0)
        match_rows.append(
            MatchMetrics(
                match_id=match_id,
                predictions_count=predictions_count,
                comments_count=comments_count,
                favorites_count=favorites_count,
                views_count=0,
                shares_count=0,
                activity_count=predictions_count + comments_count + favorites_count,
                updated_at=now,
            )
        )
    MatchMetrics.objects.bulk_create(
        match_rows,
        batch_size=1000,
        ignore_conflicts=True,
    )


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("front", "0010_articlecategory_article_is_main_and_more"),
        ("game", "0023_predictioncoverimage_placement"),
        ("cabinet", "0035_comment_user_created_idx"),
        ("notifications", "0005_notification_event_preferences"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.CreateModel(
            name="PredictionMetrics",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("likes_count", models.PositiveIntegerField(default=0, verbose_name="Лайки")),
                ("comments_count", models.PositiveIntegerField(default=0, verbose_name="Комментарии")),
                ("favorites_count", models.PositiveIntegerField(default=0, verbose_name="Избранное")),
                ("views_count", models.PositiveIntegerField(default=0, verbose_name="Просмотры")),
                ("shares_count", models.PositiveIntegerField(default=0, verbose_name="Репосты")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлено")),
                (
                    "coupon",
                    models.OneToOneField(
                        on_delete=models.deletion.CASCADE,
                        related_name="metrics",
                        to="game.predictioncoupon",
                        verbose_name="Прогноз",
                    ),
                ),
            ],
            options={
                "verbose_name": "Метрики прогноза",
                "verbose_name_plural": "Метрики прогнозов",
            },
        ),
        migrations.CreateModel(
            name="MatchMetrics",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("predictions_count", models.PositiveIntegerField(default=0, verbose_name="Прогнозы")),
                ("comments_count", models.PositiveIntegerField(default=0, verbose_name="Комментарии")),
                ("favorites_count", models.PositiveIntegerField(default=0, verbose_name="Избранное")),
                ("views_count", models.PositiveIntegerField(default=0, verbose_name="Просмотры")),
                ("shares_count", models.PositiveIntegerField(default=0, verbose_name="Репосты")),
                ("activity_count", models.PositiveIntegerField(default=0, verbose_name="Активность")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлено")),
                (
                    "match",
                    models.OneToOneField(
                        on_delete=models.deletion.CASCADE,
                        related_name="metrics",
                        to="game.match",
                        verbose_name="Матч",
                    ),
                ),
            ],
            options={
                "verbose_name": "Метрики матча",
                "verbose_name_plural": "Метрики матчей",
            },
        ),
        migrations.RunPython(backfill_metrics, noop_reverse),
    ]
