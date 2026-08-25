import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cabinet", "0002_analystprofile"),
    ]

    operations = [
        migrations.CreateModel(
            name="AnalystFollow",
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
                    "created_at",
                    models.DateTimeField(auto_now_add=True, verbose_name="Дата подписки"),
                ),
                (
                    "analyst",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="analyst_followers",
                        to="cabinet.user",
                        verbose_name="Аналитик",
                    ),
                ),
                (
                    "follower",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="analyst_follows",
                        to="cabinet.user",
                        verbose_name="Подписчик",
                    ),
                ),
            ],
            options={
                "verbose_name": "Подписка на аналитика",
                "verbose_name_plural": "Подписки на аналитиков",
                "ordering": ("-created_at",),
                "indexes": [
                    models.Index(
                        fields=["analyst", "created_at"],
                        name="follow_analyst_created_idx",
                    ),
                    models.Index(
                        fields=["follower", "created_at"],
                        name="follow_follower_created_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("follower", "analyst"),
                        name="unique_analyst_follow",
                    )
                ],
            },
        ),
    ]
