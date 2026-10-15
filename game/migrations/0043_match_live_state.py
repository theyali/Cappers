from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("game", "0042_comparisonbookmaker")]

    operations = [
        migrations.AddField(
            model_name="match", name="live_state_updated_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="match", name="live_state_needs_refresh",
            field=models.BooleanField(db_index=True, default=False),
        ),
        migrations.AlterField(
            model_name="match", name="sync_scope",
            field=models.CharField(max_length=16, choices=[
                ("live", "Идет"), ("connection_lost", "Нет связи со скаутом"),
                ("prematch", "Скоро"), ("finished", "Завершен"),
                ("postponed", "Отложен"), ("canceled", "Отменен"),
                ("forfeit", "Техническая победа"), ("interrupted", "Прерван"),
                ("abandoned", "Прерван окончательно"),
            ]),
        ),
    ]
