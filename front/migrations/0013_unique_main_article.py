from django.db import migrations, models


def keep_single_main_article(apps, schema_editor):
    Article = apps.get_model("front", "Article")
    main_ids = list(
        Article.objects.filter(is_main=True)
        .order_by("-created_at", "-id")
        .values_list("id", flat=True)
    )
    if len(main_ids) > 1:
        Article.objects.filter(is_main=True).exclude(pk=main_ids[0]).update(is_main=False)


class Migration(migrations.Migration):
    dependencies = [
        ("front", "0012_reaction_query_indexes"),
    ]

    operations = [
        migrations.RunPython(keep_single_main_article, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="article",
            constraint=models.UniqueConstraint(
                fields=("is_main",),
                condition=models.Q(is_main=True),
                name="unique_main_article",
            ),
        ),
    ]
