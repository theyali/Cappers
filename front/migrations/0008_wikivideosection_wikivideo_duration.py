from django.db import migrations, models
import django.db.models.deletion


def _section_icon(name):
    value = (name or "").casefold()
    if "аккаун" in value or "профил" in value:
        return "account"
    if "прогноз" in value or "ставк" in value:
        return "predictions"
    if "коп" in value:
        return "copybetting"
    if "уведом" in value:
        return "notifications"
    if "telegram" in value or "телег" in value:
        return "telegram"
    return "general"


def _section_order(icon):
    return {
        "account": 10,
        "predictions": 20,
        "copybetting": 30,
        "notifications": 40,
        "telegram": 50,
        "general": 100,
    }.get(icon, 100)


def move_sections_forward(apps, schema_editor):
    WikiVideo = apps.get_model("front", "WikiVideo")
    WikiVideoSection = apps.get_model("front", "WikiVideoSection")
    cache = {}

    for video in WikiVideo.objects.all().iterator():
        name = (video.legacy_section or "").strip() or "Общее"
        section = cache.get(name)
        if section is None:
            icon = _section_icon(name)
            section, _ = WikiVideoSection.objects.get_or_create(
                name=name,
                defaults={
                    "icon": icon,
                    "sort_order": _section_order(icon),
                    "is_active": True,
                },
            )
            cache[name] = section
        video.section_id = section.pk
        video.save(update_fields=("section",))


def move_sections_backward(apps, schema_editor):
    WikiVideo = apps.get_model("front", "WikiVideo")
    for video in WikiVideo.objects.select_related("section").all().iterator():
        video.legacy_section = video.section.name if video.section_id else "Общее"
        video.save(update_fields=("legacy_section",))


class Migration(migrations.Migration):

    dependencies = [
        ("front", "0007_wiki_content"),
    ]

    operations = [
        migrations.CreateModel(
            name="WikiVideoSection",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=160, unique=True, verbose_name="Название")),
                (
                    "icon",
                    models.CharField(
                        choices=[
                            ("general", "Общее"),
                            ("account", "Аккаунт"),
                            ("predictions", "Прогнозы"),
                            ("copybetting", "Копибеттинг"),
                            ("notifications", "Уведомления"),
                            ("telegram", "Telegram"),
                        ],
                        default="general",
                        max_length=24,
                        verbose_name="Иконка",
                    ),
                ),
                ("is_active", models.BooleanField(db_index=True, default=True, verbose_name="Активен")),
                ("sort_order", models.PositiveSmallIntegerField(db_index=True, default=100, verbose_name="Порядок")),
            ],
            options={
                "verbose_name": "Wiki: раздел видео",
                "verbose_name_plural": "Wiki: разделы видео",
                "ordering": ("sort_order", "name", "id"),
            },
        ),
        migrations.RenameField(
            model_name="wikivideo",
            old_name="section",
            new_name="legacy_section",
        ),
        migrations.AddField(
            model_name="wikivideo",
            name="duration",
            field=models.CharField(blank=True, help_text="Например: 5:18", max_length=12, verbose_name="Длительность"),
        ),
        migrations.AddField(
            model_name="wikivideo",
            name="section",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="videos",
                to="front.wikivideosection",
                verbose_name="Раздел",
            ),
        ),
        migrations.RunPython(move_sections_forward, move_sections_backward),
        migrations.RemoveField(
            model_name="wikivideo",
            name="legacy_section",
        ),
        migrations.AlterField(
            model_name="wikivideo",
            name="section",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="videos",
                to="front.wikivideosection",
                verbose_name="Раздел",
            ),
        ),
        migrations.AlterModelOptions(
            name="wikivideo",
            options={
                "ordering": ("section_id", "sort_order", "title", "id"),
                "verbose_name": "Wiki: видео",
                "verbose_name_plural": "Wiki: видео",
            },
        ),
    ]
