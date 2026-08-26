# Generated manually for Article support.

from django.db import migrations, models
import tinymce.models


class Migration(migrations.Migration):

    dependencies = [
        ("front", "0001_prediction_reactions"),
    ]

    operations = [
        migrations.CreateModel(
            name="Article",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=220, verbose_name="Заголовок")),
                ("slug", models.SlugField(max_length=240, unique=True, verbose_name="Slug")),
                ("description", models.TextField(max_length=700, verbose_name="Краткое описание")),
                ("image", models.ImageField(blank=True, null=True, upload_to="articles/%Y/%m/", verbose_name="Изображение")),
                ("content", tinymce.models.HTMLField(verbose_name="Контент")),
                ("is_published", models.BooleanField(db_index=True, default=True, verbose_name="Опубликована")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="Создана")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлена")),
            ],
            options={
                "verbose_name": "Статья",
                "verbose_name_plural": "Статьи",
                "ordering": ("-created_at", "-id"),
            },
        ),
    ]
