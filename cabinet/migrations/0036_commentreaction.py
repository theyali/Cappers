from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("cabinet", "0035_comment_user_created_idx"),
    ]

    operations = [
        migrations.CreateModel(
            name="CommentReaction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("like", "Лайк"), ("dislike", "Дизлайк")], max_length=8, verbose_name="Реакция")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создана")),
                ("comment", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="reactions", to="cabinet.comment", verbose_name="Комментарий")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="comment_reactions", to=settings.AUTH_USER_MODEL, verbose_name="Пользователь")),
            ],
            options={
                "verbose_name": "Реакция на комментарий",
                "verbose_name_plural": "Реакции на комментарии",
            },
        ),
        migrations.AddIndex(
            model_name="commentreaction",
            index=models.Index(fields=["comment", "kind"], name="comment_reaction_kind_idx"),
        ),
        migrations.AddConstraint(
            model_name="commentreaction",
            constraint=models.UniqueConstraint(fields=("comment", "user"), name="unique_comment_reaction_user"),
        ),
    ]
