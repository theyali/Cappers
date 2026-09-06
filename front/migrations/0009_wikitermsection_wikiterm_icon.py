from django.db import migrations, models
import django.db.models.deletion


def _section_meta(name):
    value = (name or "").casefold()
    if "аккаун" in value or "профил" in value:
        return "account", "blue", 10
    if "став" in value or "прогноз" in value:
        return "bets", "slate", 20
    if "коэфф" in value:
        return "odds", "yellow", 30
    if "стат" in value:
        return "stats", "slate", 40
    if "подпис" in value:
        return "subscriptions", "blue", 50
    if "коп" in value:
        return "copybetting", "yellow", 60
    if "баланс" in value or "кошел" in value:
        return "balance", "yellow", 70
    if "турнир" in value:
        return "tournaments", "slate", 80
    return "general", "light", 100


def _term_icon(term):
    value = (term or "").casefold()
    if "уведом" in value or "оповещ" in value:
        return "bell"
    if "провер" in value or "вериф" in value or "галоч" in value:
        return "check"
    if "турнир" in value:
        return "trophy"
    if "коэфф" in value or "кф" in value:
        return "percent"
    if "коп" in value:
        return "copy"
    if "закры" in value or "lock" in value:
        return "lock"
    if "избран" in value or "лайк" in value:
        return "star"
    if "баланс" in value or "кошел" in value:
        return "coins"
    if "стат" in value or "roi" in value or "проходим" in value:
        return "chart"
    if "подпис" in value:
        return "group"
    if "каппер" in value or "аналитик" in value or "пользоват" in value:
        return "user"
    if "став" in value or "прогноз" in value:
        return "gamepad"
    return "info"


def move_term_sections_forward(apps, schema_editor):
    WikiTerm = apps.get_model("front", "WikiTerm")
    WikiTermSection = apps.get_model("front", "WikiTermSection")
    cache = {}

    for item in WikiTerm.objects.all().iterator():
        name = (item.legacy_section or "").strip() or "Другое"
        section = cache.get(name)
        if section is None:
            icon, accent, sort_order = _section_meta(name)
            section, _ = WikiTermSection.objects.get_or_create(
                name=name,
                defaults={
                    "icon": icon,
                    "accent": accent,
                    "is_active": True,
                    "sort_order": sort_order,
                },
            )
            cache[name] = section

        item.section_id = section.pk
        item.icon = _term_icon(item.term)
        item.save(update_fields=("section", "icon"))


def move_term_sections_backward(apps, schema_editor):
    WikiTerm = apps.get_model("front", "WikiTerm")
    for item in WikiTerm.objects.select_related("section").all().iterator():
        item.legacy_section = item.section.name if item.section_id else "Другое"
        item.save(update_fields=("legacy_section",))


class Migration(migrations.Migration):

    dependencies = [
        ("front", "0008_wikivideosection_wikivideo_duration"),
    ]

    operations = [
        migrations.CreateModel(
            name="WikiTermSection",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=160, unique=True, verbose_name="Название")),
                (
                    "icon",
                    models.CharField(
                        choices=[
                            ("general", "Другое"),
                            ("account", "Аккаунт"),
                            ("bets", "Ставки"),
                            ("odds", "Коэффициенты"),
                            ("stats", "Статистика"),
                            ("subscriptions", "Подписки"),
                            ("copybetting", "Копибеттинг"),
                            ("balance", "Баланс"),
                            ("tournaments", "Турниры"),
                        ],
                        default="general",
                        max_length=24,
                        verbose_name="Иконка",
                    ),
                ),
                (
                    "accent",
                    models.CharField(
                        choices=[
                            ("blue", "Синий"),
                            ("yellow", "Жёлтый"),
                            ("slate", "Серый"),
                            ("light", "Светлый"),
                        ],
                        default="blue",
                        max_length=16,
                        verbose_name="Цвет",
                    ),
                ),
                ("is_active", models.BooleanField(db_index=True, default=True, verbose_name="Активен")),
                ("sort_order", models.PositiveSmallIntegerField(db_index=True, default=100, verbose_name="Порядок")),
            ],
            options={
                "verbose_name": "Wiki: раздел терминов",
                "verbose_name_plural": "Wiki: разделы терминов",
                "ordering": ("sort_order", "name", "id"),
            },
        ),
        migrations.RenameField(
            model_name="wikiterm",
            old_name="section",
            new_name="legacy_section",
        ),
        migrations.AddField(
            model_name="wikiterm",
            name="icon",
            field=models.CharField(
                choices=[
                    ("user", "Пользователь"),
                    ("group", "Пользователи"),
                    ("coins", "Монеты"),
                    ("chart", "Статистика"),
                    ("copy", "Копирование"),
                    ("lock", "Закрытый прогноз"),
                    ("star", "Избранное"),
                    ("bell", "Уведомления"),
                    ("check", "Проверка"),
                    ("trophy", "Турнир"),
                    ("gamepad", "Ставка"),
                    ("percent", "Коэффициент"),
                    ("wallet", "Баланс"),
                    ("info", "Информация"),
                ],
                default="info",
                max_length=24,
                verbose_name="Иконка",
            ),
        ),
        migrations.AddField(
            model_name="wikiterm",
            name="section",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="terms",
                to="front.wikitermsection",
                verbose_name="Раздел",
            ),
        ),
        migrations.RunPython(move_term_sections_forward, move_term_sections_backward),
        migrations.RemoveField(
            model_name="wikiterm",
            name="legacy_section",
        ),
        migrations.AlterField(
            model_name="wikiterm",
            name="section",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="terms",
                to="front.wikitermsection",
                verbose_name="Раздел",
            ),
        ),
        migrations.AlterModelOptions(
            name="wikiterm",
            options={
                "ordering": ("section_id", "sort_order", "term", "id"),
                "verbose_name": "Wiki: термин",
                "verbose_name_plural": "Wiki: словарь",
            },
        ),
    ]
