# Generated manually for Wiki videos and dictionary support.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("front", "0006_remove_self_prediction_reactions"),
    ]

    operations = [
        migrations.CreateModel(
            name="WikiVideo",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=220, verbose_name="Название")),
                ("section", models.CharField(db_index=True, max_length=160, verbose_name="Раздел")),
                ("description", models.TextField(max_length=700, verbose_name="Краткое описание")),
                ("video", models.FileField(upload_to="wiki/videos/%Y/%m/", verbose_name="Видео")),
                ("preview_image", models.ImageField(blank=True, null=True, upload_to="wiki/previews/%Y/%m/", verbose_name="Preview image")),
                ("is_published", models.BooleanField(db_index=True, default=True, verbose_name="Опубликовано")),
                ("sort_order", models.PositiveSmallIntegerField(db_index=True, default=100, verbose_name="Порядок")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создано")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлено")),
            ],
            options={
                "verbose_name": "Wiki: видео",
                "verbose_name_plural": "Wiki: видео",
                "ordering": ("section", "sort_order", "title", "id"),
            },
        ),
        migrations.CreateModel(
            name="WikiTerm",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("term", models.CharField(max_length=180, unique=True, verbose_name="Термин")),
                ("section", models.CharField(db_index=True, max_length=160, verbose_name="Раздел")),
                ("description", models.TextField(verbose_name="Описание")),
                ("is_published", models.BooleanField(db_index=True, default=True, verbose_name="Опубликовано")),
                ("sort_order", models.PositiveSmallIntegerField(db_index=True, default=100, verbose_name="Порядок")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создано")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлено")),
            ],
            options={
                "verbose_name": "Wiki: термин",
                "verbose_name_plural": "Wiki: словарь",
                "ordering": ("section", "sort_order", "term", "id"),
            },
        ),
    ]
