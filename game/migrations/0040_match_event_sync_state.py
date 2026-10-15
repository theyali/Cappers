from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("game", "0039_matchevent_matcheventparticipant_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="match",
            name="events_available",
            field=models.BooleanField(
                blank=True,
                null=True,
                verbose_name="События доступны у провайдера",
            ),
        ),
        migrations.AddField(
            model_name="match",
            name="events_fetched_at",
            field=models.DateTimeField(
                blank=True,
                db_index=True,
                null=True,
                verbose_name="События получены",
            ),
        ),
    ]
