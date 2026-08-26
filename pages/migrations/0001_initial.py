from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="PageSEO",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=160, verbose_name="Название страницы в админке")),
                ("route_name", models.CharField(db_index=True, help_text="Например: front:index, front:article_detail, game:match_detail.", max_length=160, verbose_name="Django view name")),
                ("exact_path", models.CharField(blank=True, default="", help_text="Необязательно. Например /articles/my-article/. Если пусто — настройки работают для всего view.", max_length=500, verbose_name="Точный URL-путь")),
                ("meta_title", models.CharField(blank=True, max_length=255, verbose_name="SEO title")),
                ("meta_description", models.TextField(blank=True, verbose_name="SEO description")),
                ("meta_keywords", models.TextField(blank=True, help_text="Ключевые слова через запятую. Поле необязательное.", verbose_name="SEO keywords")),
                ("canonical_url", models.URLField(blank=True, help_text="Если не заполнено, canonical строится автоматически из текущего URL без query string.", max_length=600, verbose_name="Canonical URL")),
                ("robots", models.CharField(choices=[("index,follow", "index, follow"), ("index,nofollow", "index, nofollow"), ("noindex,follow", "noindex, follow"), ("noindex,nofollow", "noindex, nofollow")], default="index,follow", max_length=32, verbose_name="Robots")),
                ("og_title", models.CharField(blank=True, max_length=255, verbose_name="Open Graph title")),
                ("og_description", models.TextField(blank=True, verbose_name="Open Graph description")),
                ("og_image", models.ImageField(blank=True, upload_to="seo/og/", verbose_name="Open Graph image")),
                ("og_type", models.CharField(choices=[("website", "Website"), ("article", "Article"), ("profile", "Profile")], default="website", max_length=32, verbose_name="Open Graph type")),
                ("twitter_card", models.CharField(choices=[("summary", "Summary"), ("summary_large_image", "Summary large image")], default="summary_large_image", max_length=32, verbose_name="Twitter card")),
                ("schema_type", models.CharField(blank=True, default="WebPage", help_text="Например WebPage, Article, ProfilePage, SportsEvent.", max_length=100, verbose_name="Schema.org type")),
                ("schema_json_ld", models.TextField(blank=True, help_text="Необязательный JSON-объект. Будет выведен как application/ld+json.", verbose_name="Дополнительный JSON-LD")),
                ("is_active", models.BooleanField(db_index=True, default=True, verbose_name="Использовать SEO-настройки")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Обновлено")),
            ],
            options={
                "verbose_name": "SEO страницы",
                "verbose_name_plural": "SEO страниц",
                "ordering": ("route_name", "exact_path", "name"),
                "indexes": [models.Index(fields=["route_name", "is_active"], name="pages_seo_route_active_idx")],
                "constraints": [models.UniqueConstraint(fields=("route_name", "exact_path"), name="pages_seo_route_path_unique")],
            },
        ),
    ]
