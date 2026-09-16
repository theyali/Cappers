from django.db import migrations, models
import django.db.models.deletion
from django.db.models import Count
from django.utils import timezone


def backfill_comment_metrics(apps, schema_editor):
    Comment = apps.get_model("cabinet", "Comment")
    CommentReaction = apps.get_model("cabinet", "CommentReaction")
    CommentMetrics = apps.get_model("cabinet", "CommentMetrics")

    reaction_counts = {}
    for row in (
        CommentReaction.objects.values("comment_id", "kind")
        .annotate(total=Count("id"))
        .order_by()
    ):
        reaction_counts[(row["comment_id"], row["kind"])] = int(row["total"] or 0)

    replies_counts = {
        row["parent_id"]: int(row["total"] or 0)
        for row in (
            Comment.objects.filter(
                parent_id__isnull=False,
                status="published",
            )
            .values("parent_id")
            .annotate(total=Count("id"))
            .order_by()
        )
    }

    now = timezone.now()
    metrics = []
    for comment_id in Comment.objects.values_list("id", flat=True).iterator():
        metrics.append(
            CommentMetrics(
                comment_id=comment_id,
                likes_count=reaction_counts.get((comment_id, "like"), 0),
                dislikes_count=reaction_counts.get((comment_id, "dislike"), 0),
                replies_count=replies_counts.get(comment_id, 0),
                updated_at=now,
            )
        )
        if len(metrics) >= 1000:
            CommentMetrics.objects.bulk_create(metrics, ignore_conflicts=True)
            metrics = []

    if metrics:
        CommentMetrics.objects.bulk_create(metrics, ignore_conflicts=True)


class Migration(migrations.Migration):

    dependencies = [
        ("cabinet", "0036_commentreaction"),
    ]

    operations = [
        migrations.CreateModel(
            name="CommentMetrics",
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
                ("likes_count", models.PositiveIntegerField(default=0, verbose_name="Лайки")),
                (
                    "dislikes_count",
                    models.PositiveIntegerField(default=0, verbose_name="Дизлайки"),
                ),
                ("replies_count", models.PositiveIntegerField(default=0, verbose_name="Ответы")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлено")),
                (
                    "comment",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="metrics",
                        to="cabinet.comment",
                        verbose_name="Комментарий",
                    ),
                ),
            ],
            options={
                "verbose_name": "Метрики комментария",
                "verbose_name_plural": "Метрики комментариев",
            },
        ),
        migrations.RunPython(backfill_comment_metrics, migrations.RunPython.noop),
    ]
