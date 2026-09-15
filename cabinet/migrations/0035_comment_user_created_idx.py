from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cabinet", "0034_comment"),
    ]

    operations = [
        migrations.AddIndex(
            model_name="comment",
            index=models.Index(
                fields=["user", "created_at"],
                name="comment_user_created_idx",
            ),
        ),
    ]
