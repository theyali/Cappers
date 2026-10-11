from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("cabinet", "0069_remove_analystprofile_cover_image"),
        ("game", "0037_predictioncoverimage_mobile_image"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="gender",
            field=models.CharField(
                blank=True,
                choices=[("male", "Мужской"), ("female", "Женский")],
                max_length=10,
                verbose_name="Пол",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="country",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="users",
                to="game.country",
                verbose_name="Страна",
            ),
        ),
    ]
