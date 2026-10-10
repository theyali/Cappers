from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import tinymce.models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("front", "0016_static_page_public_document_aliases"),
    ]

    operations = [
        migrations.AddField(
            model_name="wikivideo",
            name="slug",
            field=models.SlugField(
                allow_unicode=True,
                blank=True,
                max_length=240,
                null=True,
                unique=True,
                verbose_name="Slug",
            ),
        ),
        migrations.AlterField(
            model_name="wikivideo",
            name="description",
            field=tinymce.models.HTMLField(verbose_name="Описание"),
        ),
        migrations.AddField(
            model_name="wikivideo",
            name="tags",
            field=models.CharField(blank=True, help_text="Через запятую", max_length=300, verbose_name="Теги"),
        ),
        migrations.AddField(
            model_name="wikivideo",
            name="views_count",
            field=models.PositiveIntegerField(default=0, verbose_name="Просмотры"),
        ),
        migrations.AddField(
            model_name="wikivideo",
            name="likes_count",
            field=models.PositiveIntegerField(default=0, verbose_name="Лайки"),
        ),
        migrations.AddField(
            model_name="wikivideo",
            name="dislikes_count",
            field=models.PositiveIntegerField(default=0, verbose_name="Дизлайки"),
        ),
        migrations.CreateModel(
            name="WikiVideoReaction",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "kind",
                    models.CharField(
                        choices=[("like", "Лайк"), ("dislike", "Дизлайк")],
                        max_length=12,
                        verbose_name="Реакция",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создана")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлена")),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="wiki_video_reactions",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Пользователь",
                    ),
                ),
                (
                    "video",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="user_reactions",
                        to="front.wikivideo",
                        verbose_name="Видео",
                    ),
                ),
            ],
            options={
                "verbose_name": "Wiki: реакция на видео",
                "verbose_name_plural": "Wiki: реакции на видео",
                "ordering": ("-updated_at",),
            },
        ),
        migrations.CreateModel(
            name="WikiVideoProgress",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("position_seconds", models.PositiveIntegerField(default=0, verbose_name="Позиция, сек")),
                ("duration_seconds", models.PositiveIntegerField(default=0, verbose_name="Длительность, сек")),
                ("completed", models.BooleanField(db_index=True, default=False, verbose_name="Просмотрено")),
                ("completed_at", models.DateTimeField(blank=True, null=True, verbose_name="Просмотрено в")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создано")),
                ("last_watched_at", models.DateTimeField(auto_now=True, verbose_name="Последний просмотр")),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="wiki_video_progress",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Пользователь",
                    ),
                ),
                (
                    "video",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="user_progress",
                        to="front.wikivideo",
                        verbose_name="Видео",
                    ),
                ),
            ],
            options={
                "verbose_name": "Wiki: прогресс видео",
                "verbose_name_plural": "Wiki: прогресс видео",
                "ordering": ("-last_watched_at",),
            },
        ),
        migrations.AddIndex(
            model_name="wikivideo",
            index=models.Index(fields=["is_published", "created_at"], name="wiki_video_pub_created_idx"),
        ),
        migrations.AddIndex(
            model_name="wikivideo",
            index=models.Index(fields=["section", "is_published", "sort_order"], name="wiki_video_section_sort_idx"),
        ),
        migrations.AddIndex(
            model_name="wikivideoreaction",
            index=models.Index(fields=["video", "kind"], name="wiki_video_react_kind_idx"),
        ),
        migrations.AddIndex(
            model_name="wikivideoreaction",
            index=models.Index(fields=["user", "updated_at"], name="wiki_video_react_user_idx"),
        ),
        migrations.AddIndex(
            model_name="wikivideoprogress",
            index=models.Index(fields=["user", "last_watched_at"], name="wiki_video_prog_user_idx"),
        ),
        migrations.AddIndex(
            model_name="wikivideoprogress",
            index=models.Index(fields=["video", "last_watched_at"], name="wiki_video_prog_video_idx"),
        ),
        migrations.AddConstraint(
            model_name="wikivideoreaction",
            constraint=models.UniqueConstraint(fields=("video", "user"), name="unique_wiki_video_reaction"),
        ),
        migrations.AddConstraint(
            model_name="wikivideoprogress",
            constraint=models.UniqueConstraint(fields=("video", "user"), name="unique_wiki_video_progress"),
        ),
    ]
