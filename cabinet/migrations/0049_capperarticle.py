import django.db.models.deletion
import tinymce.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cabinet", "0048_analystprofile_cover_image"),
    ]

    operations = [
        migrations.CreateModel(
            name="CapperArticle",
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
                (
                    "title",
                    models.CharField(max_length=180, verbose_name="Заголовок"),
                ),
                (
                    "slug",
                    models.SlugField(blank=True, max_length=220, verbose_name="Slug"),
                ),
                (
                    "cover_image",
                    models.ImageField(
                        blank=True,
                        upload_to="capper_articles/%Y/%m/",
                        verbose_name="Обложка",
                    ),
                ),
                (
                    "excerpt",
                    models.TextField(blank=True, verbose_name="Краткое описание"),
                ),
                (
                    "content",
                    tinymce.models.HTMLField(verbose_name="Контент"),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("draft", "Черновик"),
                            ("pending", "На модерации"),
                            ("approved", "Опубликована"),
                            ("rejected", "Отклонена"),
                        ],
                        db_index=True,
                        default="draft",
                        max_length=16,
                        verbose_name="Статус",
                    ),
                ),
                (
                    "moderation_note",
                    models.TextField(
                        blank=True,
                        verbose_name="Комментарий модератора",
                    ),
                ),
                (
                    "submitted_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                        verbose_name="Отправлена на модерацию",
                    ),
                ),
                (
                    "published_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                        verbose_name="Опубликована",
                    ),
                ),
                (
                    "reviewed_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                        verbose_name="Проверена",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, verbose_name="Создана"),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True, verbose_name="Обновлена"),
                ),
                (
                    "author",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="capper_articles",
                        to="cabinet.user",
                        verbose_name="Автор",
                    ),
                ),
                (
                    "reviewed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="cabinet.user",
                        verbose_name="Проверил",
                    ),
                ),
            ],
            options={
                "verbose_name": "Статья каппера",
                "verbose_name_plural": "Статьи капперов",
                "ordering": ("-created_at", "-id"),
            },
        ),
    ]
