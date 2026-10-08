from django.db import migrations

# (group title, link title, url, order): first in their groups.
LINKS = (
    ("Сервис", "О нас", "/about/", 5),
    ("Документы", "Правила", "/rules/", 5),
)


def add_links(apps, schema_editor):
    FooterLinkGroup = apps.get_model("back", "FooterLinkGroup")
    FooterLink = apps.get_model("back", "FooterLink")
    for group_title, title, url, order in LINKS:
        group = FooterLinkGroup.objects.filter(title=group_title).first()
        if group is None or FooterLink.objects.filter(group=group, url=url).exists():
            continue
        FooterLink.objects.create(group=group, title=title, url=url, order=order, is_active=True)


def remove_links(apps, schema_editor):
    FooterLink = apps.get_model("back", "FooterLink")
    for group_title, title, url, _order in LINKS:
        FooterLink.objects.filter(group__title=group_title, title=title, url=url).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("back", "0014_websitesettings_referral_income_days_and_more"),
    ]

    operations = [
        migrations.RunPython(add_links, remove_links),
    ]
