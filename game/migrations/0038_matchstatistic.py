from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("game", "0037_predictioncoverimage_mobile_image"),
    ]

    operations = [
        migrations.CreateModel(
            name="MatchStatistic",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("period_code", models.CharField(blank=True, db_index=True, max_length=64, verbose_name="Код периода")),
                ("period_name", models.CharField(blank=True, max_length=128, verbose_name="Период")),
                ("stat_code", models.CharField(db_index=True, max_length=96, verbose_name="Код статистики")),
                ("stat_name", models.CharField(blank=True, max_length=128, verbose_name="Название")),
                ("stat_name_ru", models.CharField(blank=True, max_length=128, verbose_name="Название RU")),
                ("category", models.CharField(blank=True, max_length=64, verbose_name="Категория")),
                ("unit", models.CharField(blank=True, max_length=32, verbose_name="Единица")),
                ("value_type", models.CharField(blank=True, max_length=32, verbose_name="Тип значения")),
                ("home_value", models.DecimalField(blank=True, decimal_places=3, max_digits=12, null=True, verbose_name="Значение хозяев")),
                ("away_value", models.DecimalField(blank=True, decimal_places=3, max_digits=12, null=True, verbose_name="Значение гостей")),
                ("home_display", models.CharField(blank=True, max_length=32, verbose_name="Отображение хозяев")),
                ("away_display", models.CharField(blank=True, max_length=32, verbose_name="Отображение гостей")),
                ("sort_order", models.PositiveSmallIntegerField(default=100, verbose_name="Порядок")),
                ("raw_data", models.JSONField(blank=True, default=dict)),
                ("fetched_at", models.DateTimeField(blank=True, db_index=True, null=True, verbose_name="Получено")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлено")),
                ("match", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="statistics_rows", to="game.match", verbose_name="Матч")),
            ],
            options={
                "verbose_name": "Статистика матча",
                "verbose_name_plural": "Статистика матчей",
                "ordering": ("match_id", "period_code", "sort_order", "stat_name_ru", "stat_name", "id"),
            },
        ),
        migrations.AddConstraint(
            model_name="matchstatistic",
            constraint=models.UniqueConstraint(fields=("match", "period_code", "stat_code"), name="unique_match_stat_period_code"),
        ),
        migrations.AddIndex(
            model_name="matchstatistic",
            index=models.Index(fields=["match", "period_code", "sort_order"], name="match_stat_match_period_idx"),
        ),
        migrations.AddIndex(
            model_name="matchstatistic",
            index=models.Index(fields=["stat_code"], name="match_stat_code_idx"),
        ),
    ]
