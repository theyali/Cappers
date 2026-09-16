from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("front", "0011_prediction_match_metrics"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                "CREATE INDEX IF NOT EXISTS pred_like_user_pred_idx "
                "ON front_predictionlike (user_id, prediction_id);"
            ),
            reverse_sql="DROP INDEX IF EXISTS pred_like_user_pred_idx;",
        ),
        migrations.RunSQL(
            sql=(
                "CREATE INDEX IF NOT EXISTS pred_fav_user_pred_idx "
                "ON front_predictionfavorite (user_id, prediction_id);"
            ),
            reverse_sql="DROP INDEX IF EXISTS pred_fav_user_pred_idx;",
        ),
    ]
