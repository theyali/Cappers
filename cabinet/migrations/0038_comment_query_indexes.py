from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("cabinet", "0037_commentmetrics"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                "CREATE INDEX IF NOT EXISTS comment_target_parent_idx "
                "ON cabinet_comment "
                "(content_type_id, object_id, status, parent_id, created_at);"
            ),
            reverse_sql="DROP INDEX IF EXISTS comment_target_parent_idx;",
        ),
        migrations.RunSQL(
            sql=(
                "CREATE INDEX IF NOT EXISTS comment_react_user_comment_idx "
                "ON cabinet_commentreaction (user_id, comment_id);"
            ),
            reverse_sql="DROP INDEX IF EXISTS comment_react_user_comment_idx;",
        ),
    ]
