from django.db import migrations, models


DEFAULT_FAQ = (
    (
        "Кто может участвовать в турнире?",
        "Участвовать могут пользователи, которые соответствуют условиям доступа турнира.",
    ),
    (
        "Как считается прибыль?",
        "Прибыль считается по завершённым прогнозам с учётом суммы ставки, выигрышей и проигрышей.",
    ),
    (
        "Когда выплачиваются призы?",
        "Призы начисляются после окончания турнира и проверки итоговых результатов.",
    ),
)


def seed_default_faq(apps, schema_editor):
    TournamentFAQ = apps.get_model("tournaments", "TournamentFAQ")
    items = [
        TournamentFAQ(question=question, answer=answer, sort_order=index * 10, is_active=True)
        for index, (question, answer) in enumerate(DEFAULT_FAQ, start=1)
    ]
    TournamentFAQ.objects.bulk_create(items)


def remove_default_faq(apps, schema_editor):
    TournamentFAQ = apps.get_model("tournaments", "TournamentFAQ")
    TournamentFAQ.objects.filter(question__in=[question for question, _ in DEFAULT_FAQ]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("tournaments", "0011_alter_tournamentprize_options"),
    ]

    operations = [
        migrations.CreateModel(
            name="TournamentFAQ",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("question", models.CharField(max_length=220, verbose_name="Вопрос")),
                ("answer", models.TextField(verbose_name="Ответ")),
                ("sort_order", models.PositiveIntegerField(default=0, verbose_name="Порядок")),
                ("is_active", models.BooleanField(default=True, verbose_name="Активен")),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Создан")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлён")),
            ],
            options={
                "verbose_name": "FAQ турниров",
                "verbose_name_plural": "FAQ турниров",
                "ordering": ("sort_order", "id"),
                "indexes": [models.Index(fields=["is_active", "sort_order"], name="tournaments_is_acti_a759bd_idx")],
            },
        ),
        migrations.RunPython(seed_default_faq, remove_default_faq),
    ]
