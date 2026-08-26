from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("game", "0013_match_odds_resolved_at_match_odds_result_data_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="prediction",
            name="confidence",
            field=models.PositiveSmallIntegerField(default=50, verbose_name="Уверенность"),
        ),
        migrations.RemoveField(
            model_name="prediction",
            name="comment",
        ),
    ]
