from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("back", "0003_home_about_settings"),
    ]

    operations = [
        migrations.AddField(
            model_name="bookmaker",
            name="description",
            field=models.CharField(blank=True, max_length=220, verbose_name="Краткое описание"),
        ),
        migrations.AddField(
            model_name="bookmaker",
            name="show_on_home",
            field=models.BooleanField(default=False, verbose_name="Показывать на главной"),
        ),
        migrations.AddField(
            model_name="bookmaker",
            name="home_order",
            field=models.PositiveIntegerField(db_index=True, default=0, verbose_name="Порядок на главной"),
        ),
    ]
