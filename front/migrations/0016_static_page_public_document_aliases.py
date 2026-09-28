# Generated manually for public document URLs.

from django.db import migrations


DOCUMENT_PAGES = (
    {
        "slug": "user-agreement",
        "source_slug": "terms",
        "title": "Пользовательское соглашение",
        "content": (
            "<p>Используя сайт, пользователь соглашается с правилами сервиса. "
            "Прогнозы публикуются в информационных целях и не являются гарантией результата.</p>"
        ),
        "footer_order": 20,
    },
    {
        "slug": "cookie-policy",
        "source_slug": "cookies",
        "title": "Политика cookies",
        "content": (
            "<p>Сайт может использовать cookies для авторизации, безопасности, "
            "аналитики и сохранения пользовательских настроек.</p>"
        ),
        "footer_order": 30,
    },
)


def create_public_document_aliases(apps, schema_editor):
    StaticPage = apps.get_model("front", "StaticPage")

    for item in DOCUMENT_PAGES:
        source = StaticPage.objects.filter(slug=item["source_slug"]).first()
        defaults = {
            "title": source.title if source else item["title"],
            "content": source.content if source else item["content"],
            "is_published": True,
            "show_in_footer": True,
            "footer_order": item["footer_order"],
        }
        StaticPage.objects.update_or_create(slug=item["slug"], defaults=defaults)


class Migration(migrations.Migration):

    dependencies = [
        ("front", "0015_newscategory_news"),
    ]

    operations = [
        migrations.RunPython(create_public_document_aliases, migrations.RunPython.noop),
    ]
