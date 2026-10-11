from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("cabinet", "0070_user_gender_country"),
    ]

    operations = [
        migrations.CreateModel(
            name="PresetAvatar",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=100, verbose_name="Название")),
                ("image", models.ImageField(upload_to="users/preset_avatars/", verbose_name="Аватар")),
                ("gender", models.CharField(
                    choices=[("all", "Для всех"), ("male", "Мужской"), ("female", "Женский")],
                    default="all", max_length=10, verbose_name="Пол",
                )),
                ("is_active", models.BooleanField(default=True, verbose_name="Доступен для выбора")),
                ("sort_order", models.PositiveSmallIntegerField(default=0, verbose_name="Порядок")),
            ],
            options={
                "verbose_name": "Готовый аватар",
                "verbose_name_plural": "Готовые аватары",
                "ordering": ("sort_order", "pk"),
            },
        ),
    ]
