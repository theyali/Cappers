from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cabinet", "0008_user_telegram_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="analystprofile",
            name="favorite_leagues",
            field=models.CharField(blank=True, max_length=500, verbose_name="Любимые лиги"),
        ),
        migrations.AddField(
            model_name="analystprofile",
            name="favorite_sports",
            field=models.CharField(blank=True, max_length=320, verbose_name="Любимые виды спорта"),
        ),
        migrations.AddField(
            model_name="analystprofile",
            name="onboarding_completed_at",
            field=models.DateTimeField(blank=True, null=True, verbose_name="Onboarding завершён"),
        ),
        migrations.AddField(
            model_name="analystprofile",
            name="specialization",
            field=models.CharField(blank=True, max_length=220, verbose_name="Специализация"),
        ),
    ]
