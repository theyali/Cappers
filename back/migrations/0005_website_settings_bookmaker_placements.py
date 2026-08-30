from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("back", "0004_bookmaker_home_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="websitesettings",
            name="match_detail_bookmaker_left",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="back.bookmaker",
                verbose_name="Матч — БК слева",
            ),
        ),
        migrations.AddField(
            model_name="websitesettings",
            name="match_detail_bookmaker_right",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="back.bookmaker",
                verbose_name="Матч — БК справа",
            ),
        ),
        migrations.AddField(
            model_name="websitesettings",
            name="prediction_bookmaker_left",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="back.bookmaker",
                verbose_name="Прогнозы — БК 1",
            ),
        ),
        migrations.AddField(
            model_name="websitesettings",
            name="prediction_bookmaker_right",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="back.bookmaker",
                verbose_name="Прогнозы — БК 2",
            ),
        ),
    ]
