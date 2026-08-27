from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0003_telegramaccount"),
    ]

    operations = [
        migrations.AddField(
            model_name="matchwatch",
            name="last_scope",
            field=models.CharField(blank=True, default="", max_length=16, verbose_name="Последний статус"),
        ),
        migrations.AddField(
            model_name="matchwatch",
            name="last_score",
            field=models.CharField(blank=True, default="", max_length=32, verbose_name="Последний счёт"),
        ),
        migrations.AddField(
            model_name="matchwatch",
            name="last_time_status",
            field=models.CharField(blank=True, default="", max_length=8, verbose_name="Последний time status"),
        ),
        migrations.AddField(
            model_name="matchwatch",
            name="started_sent_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Уведомление о старте"),
        ),
        migrations.AddField(
            model_name="matchwatch",
            name="halftime_sent_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Уведомление о перерыве"),
        ),
    ]
