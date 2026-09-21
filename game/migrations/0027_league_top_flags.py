from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("game", "0026_matchmanualreview"),
    ]

    operations = [
        migrations.AddField(
            model_name="league",
            name="is_top",
            field=models.BooleanField(db_index=True, default=False, verbose_name="Топ лига"),
        ),
        migrations.AddField(
            model_name="league",
            name="top_order",
            field=models.PositiveIntegerField(db_index=True, default=100, verbose_name="Порядок в топе"),
        ),
    ]
