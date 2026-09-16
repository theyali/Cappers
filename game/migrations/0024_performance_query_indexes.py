from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("game", "0023_predictioncoverimage_placement"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                "CREATE INDEX IF NOT EXISTS coupon_pub_aud_date_idx "
                "ON game_predictioncoupon "
                "(published_status, audience, published_at DESC, id DESC);"
            ),
            reverse_sql="DROP INDEX IF EXISTS coupon_pub_aud_date_idx;",
        ),
        migrations.RunSQL(
            sql=(
                "CREATE INDEX IF NOT EXISTS coupon_author_pub_aud_idx "
                "ON game_predictioncoupon "
                "(author_id, published_status, audience);"
            ),
            reverse_sql="DROP INDEX IF EXISTS coupon_author_pub_aud_idx;",
        ),
        migrations.RunSQL(
            sql=(
                "CREATE INDEX IF NOT EXISTS pred_cover_lookup_idx "
                "ON game_predictioncoverimage "
                "(placement, cover_type, sport_id, is_active);"
            ),
            reverse_sql="DROP INDEX IF EXISTS pred_cover_lookup_idx;",
        ),
    ]
