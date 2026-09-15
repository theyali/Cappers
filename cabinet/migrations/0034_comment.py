from django.conf import settings
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cabinet", "0033_alter_rouletteprize_reward_value"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.CreateModel(
            name="Comment",
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
                ("object_id", models.PositiveBigIntegerField(verbose_name="ID объекта")),
                ("text", models.TextField(max_length=1000, verbose_name="Комментарий")),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("published", "Опубликован"),
                            ("pending", "На модерации"),
                            ("rejected", "Отклонён"),
                            ("deleted", "Удалён"),
                        ],
                        default="published",
                        max_length=16,
                        verbose_name="Статус",
                    ),
                ),
                (
                    "moderation_reason",
                    models.CharField(
                        blank=True,
                        max_length=255,
                        verbose_name="Причина модерации",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создан")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлён")),
                (
                    "content_type",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="+",
                        to="contenttypes.contenttype",
                        verbose_name="Тип объекта",
                    ),
                ),
                (
                    "parent",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="replies",
                        to="cabinet.comment",
                        verbose_name="Родительский комментарий",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="comments",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Пользователь",
                    ),
                ),
            ],
            options={
                "verbose_name": "Комментарий",
                "verbose_name_plural": "Комментарии",
                "ordering": ("created_at", "id"),
                "indexes": [
                    models.Index(
                        fields=["content_type", "object_id", "status", "created_at"],
                        name="comment_target_status_idx",
                    ),
                ],
            },
        ),
    ]
