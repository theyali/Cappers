from django.db import migrations, models
import django.db.models.deletion
import tinymce.models


def seed_tournaments_help(apps, schema_editor):
    HelpBlock = apps.get_model("pages", "HelpBlock")
    HelpAccordionItem = apps.get_model("pages", "HelpAccordionItem")

    help_block, _ = HelpBlock.objects.get_or_create(
        key="tournaments-hero",
        defaults={
            "title": "Помощь по турнирам",
            "is_active": True,
        },
    )

    items = [
        (
            10,
            "Что такое турниры?",
            "<p>Турниры объединяют капперов в отдельное соревнование с общей таблицей участников и призовыми местами.</p>",
        ),
        (
            20,
            "Как участвовать в турнире?",
            "<p>Откройте подходящий турнир, ознакомьтесь с условиями и присоединитесь к нему, пока регистрация доступна. Прогнозы, которые подходят под правила турнира, учитываются в его статистике.</p>",
        ),
        (
            30,
            "Как определяются победители?",
            "<p>Итоговое место зависит от правил конкретного турнира и результатов прогнозов. Актуальная таблица участников доступна на странице турнира.</p>",
        ),
    ]

    for sort_order, title, content in items:
        HelpAccordionItem.objects.get_or_create(
            help_block=help_block,
            sort_order=sort_order,
            defaults={
                "title": title,
                "content": content,
                "is_active": True,
            },
        )


def unseed_tournaments_help(apps, schema_editor):
    HelpBlock = apps.get_model("pages", "HelpBlock")
    HelpBlock.objects.filter(key="tournaments-hero").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("pages", "0005_match_list_filtered_seo"),
    ]

    operations = [
        migrations.CreateModel(
            name="HelpBlock",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "key",
                    models.SlugField(
                        help_text="Передавайте этот ключ в include кнопки помощи, например tournaments-hero.",
                        max_length=120,
                        unique=True,
                        verbose_name="Ключ блока",
                    ),
                ),
                ("title", models.CharField(max_length=180, verbose_name="Заголовок модального окна")),
                ("is_active", models.BooleanField(db_index=True, default=True, verbose_name="Показывать помощь")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлено")),
            ],
            options={
                "verbose_name": "Блок помощи",
                "verbose_name_plural": "Блоки помощи",
                "ordering": ("title", "key"),
            },
        ),
        migrations.CreateModel(
            name="HelpAccordionItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=220, verbose_name="Заголовок аккордеона")),
                ("content", tinymce.models.HTMLField(verbose_name="RichText контент")),
                ("sort_order", models.PositiveSmallIntegerField(db_index=True, default=100, verbose_name="Порядок")),
                ("is_active", models.BooleanField(db_index=True, default=True, verbose_name="Показывать")),
                (
                    "help_block",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="items",
                        to="pages.helpblock",
                        verbose_name="Блок помощи",
                    ),
                ),
            ],
            options={
                "verbose_name": "Пункт помощи",
                "verbose_name_plural": "Пункты помощи",
                "ordering": ("sort_order", "id"),
            },
        ),
        migrations.AddIndex(
            model_name="helpaccordionitem",
            index=models.Index(
                fields=["help_block", "is_active", "sort_order"],
                name="pages_help_item_active_idx",
            ),
        ),
        migrations.RunPython(seed_tournaments_help, unseed_tournaments_help),
    ]
