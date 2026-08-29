from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("cabinet", "0016_cappermonthlystat_sports_data"),
    ]

    operations = [
        migrations.CreateModel(
            name="UserPresence",
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
                    "last_seen_at",
                    models.DateTimeField(
                        db_index=True,
                        verbose_name="Последняя активность",
                    ),
                ),
                (
                    "updated_at",
                    models.DateTimeField(
                        auto_now=True,
                        verbose_name="Обновлено",
                    ),
                ),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="presence",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="Пользователь",
                    ),
                ),
            ],
            options={
                "verbose_name": "Онлайн-статус пользователя",
                "verbose_name_plural": "Онлайн-статусы пользователей",
            },
        ),
    ]
