from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("back", "0011_bookmaker_catalog_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="websitesettings",
            name="robots_txt",
            field=models.TextField(
                blank=True,
                default="User-agent: *\nAllow: /\n\nSitemap: {sitemap_url}\n",
                help_text="Можно использовать {sitemap_url}; при отдаче robots.txt он заменится на абсолютную ссылку sitemap.",
                verbose_name="robots.txt",
            ),
        ),
    ]
