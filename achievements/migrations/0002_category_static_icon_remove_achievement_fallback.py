from django.db import migrations, models


CATEGORY_STATIC_ICONS = {
    "predictions": "front/img/badges/first-pick.svg",
    "wins": "front/img/badges/wins-3.svg",
    "roi": "front/img/badges/roi-5.svg",
    "audience": "front/img/badges/followers-10.svg",
    "streaks": "front/img/badges/streak-3.svg",
    "status": "front/img/badges/verified.svg",
    "referrals": "front/img/badges/referrals.svg",
    "activity": "front/img/badges/likes.svg",
}


def populate_category_static_icons(apps, schema_editor):
    AchievementCategory = apps.get_model("achievements", "AchievementCategory")
    for slug, icon in CATEGORY_STATIC_ICONS.items():
        AchievementCategory.objects.filter(slug=slug).update(
            fallback_static_icon=icon,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("achievements", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="achievementcategory",
            name="fallback_static_icon",
            field=models.CharField(
                blank=True,
                help_text="Используется для всех обычных достижений категории, если не загружена иконка.",
                max_length=255,
                verbose_name="Статическая иконка",
            ),
        ),
        migrations.RunPython(
            populate_category_static_icons,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="achievement",
            name="icon",
            field=models.ImageField(
                blank=True,
                help_text="Используется только для особых достижений с метрикой «Другое». Обычные достижения берут иконку категории.",
                upload_to="achievements/icons/",
                verbose_name="Иконка особого достижения",
            ),
        ),
        migrations.RemoveField(
            model_name="achievement",
            name="fallback_static_icon",
        ),
    ]
