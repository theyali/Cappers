from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("front", "0003_staticpage_websitesettings"),
        ("back", "0002_move_website_settings"),
    ]

    operations = [
        migrations.DeleteModel(name="WebsiteSettings"),
    ]
