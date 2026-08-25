from django.db import migrations, models
import django.db.models.deletion


def create_existing_analyst_profiles(apps, schema_editor):
    User = apps.get_model("cabinet", "User")
    AnalystProfile = apps.get_model("cabinet", "AnalystProfile")

    analyst_ids = User.objects.filter(role="analyst").values_list("id", flat=True)
    AnalystProfile.objects.bulk_create(
        [AnalystProfile(user_id=user_id) for user_id in analyst_ids],
        ignore_conflicts=True,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("cabinet", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="AnalystProfile",
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
                    "display_name",
                    models.CharField(
                        blank=True,
                        max_length=120,
                        verbose_name="Отображаемое имя",
                    ),
                ),
                (
                    "avatar",
                    models.ImageField(
                        blank=True,
                        null=True,
                        upload_to="analysts/avatars/%Y/%m/",
                        verbose_name="Аватар",
                    ),
                ),
                (
                    "bio",
                    models.TextField(
                        blank=True,
                        max_length=2000,
                        verbose_name="О себе",
                    ),
                ),
                (
                    "is_verified",
                    models.BooleanField(
                        db_index=True,
                        default=False,
                        verbose_name="Проверен",
                    ),
                ),
                (
                    "is_public",
                    models.BooleanField(
                        db_index=True,
                        default=True,
                        verbose_name="Публичный профиль",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создан")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлён")),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="analyst_profile",
                        to="cabinet.user",
                        verbose_name="Пользователь",
                    ),
                ),
            ],
            options={
                "verbose_name": "Профиль аналитика",
                "verbose_name_plural": "Профили аналитиков",
                "ordering": ("-created_at",),
            },
        ),
        migrations.RunPython(
            create_existing_analyst_profiles,
            migrations.RunPython.noop,
        ),
    ]
