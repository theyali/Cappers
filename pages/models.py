import json

from django.core.exceptions import ValidationError
from django.db import models


class PageSEO(models.Model):
    class Robots(models.TextChoices):
        INDEX_FOLLOW = "index,follow", "index, follow"
        INDEX_NOFOLLOW = "index,nofollow", "index, nofollow"
        NOINDEX_FOLLOW = "noindex,follow", "noindex, follow"
        NOINDEX_NOFOLLOW = "noindex,nofollow", "noindex, nofollow"

    class OpenGraphType(models.TextChoices):
        WEBSITE = "website", "Website"
        ARTICLE = "article", "Article"
        PROFILE = "profile", "Profile"

    class TwitterCard(models.TextChoices):
        SUMMARY = "summary", "Summary"
        LARGE = "summary_large_image", "Summary large image"

    name = models.CharField("Название страницы в админке", max_length=160)
    route_name = models.CharField(
        "Django view name",
        max_length=160,
        db_index=True,
        help_text="Например: front:index, front:article_detail, game:match_detail.",
    )
    exact_path = models.CharField(
        "Точный URL-путь",
        max_length=500,
        blank=True,
        default="",
        help_text="Необязательно. Например /articles/my-article/. Если пусто — настройки работают для всего view.",
    )
    meta_title = models.CharField("SEO title", max_length=255, blank=True)
    meta_description = models.TextField("SEO description", blank=True)
    meta_keywords = models.TextField(
        "SEO keywords",
        blank=True,
        help_text="Ключевые слова через запятую. Поле необязательное.",
    )
    canonical_url = models.URLField(
        "Canonical URL",
        max_length=600,
        blank=True,
        help_text="Если не заполнено, canonical строится автоматически из текущего URL без query string.",
    )
    robots = models.CharField(
        "Robots",
        max_length=32,
        choices=Robots.choices,
        default=Robots.INDEX_FOLLOW,
    )
    og_title = models.CharField("Open Graph title", max_length=255, blank=True)
    og_description = models.TextField("Open Graph description", blank=True)
    og_image = models.ImageField("Open Graph image", upload_to="seo/og/", blank=True)
    og_type = models.CharField(
        "Open Graph type",
        max_length=32,
        choices=OpenGraphType.choices,
        default=OpenGraphType.WEBSITE,
    )
    twitter_card = models.CharField(
        "Twitter card",
        max_length=32,
        choices=TwitterCard.choices,
        default=TwitterCard.LARGE,
    )
    schema_type = models.CharField(
        "Schema.org type",
        max_length=100,
        blank=True,
        default="WebPage",
        help_text="Например WebPage, Article, ProfilePage, SportsEvent.",
    )
    schema_json_ld = models.TextField(
        "Дополнительный JSON-LD",
        blank=True,
        help_text="Необязательный JSON-объект. Будет выведен как application/ld+json.",
    )
    is_active = models.BooleanField("Использовать SEO-настройки", default=True, db_index=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        verbose_name = "SEO страницы"
        verbose_name_plural = "SEO страниц"
        ordering = ("route_name", "exact_path", "name")
        constraints = [
            models.UniqueConstraint(
                fields=("route_name", "exact_path"),
                name="pages_seo_route_path_unique",
            )
        ]
        indexes = [
            models.Index(
                fields=("route_name", "is_active"),
                name="pages_seo_route_active_idx",
            )
        ]

    def __str__(self) -> str:
        suffix = f" · {self.exact_path}" if self.exact_path else ""
        return f"{self.name} · {self.route_name}{suffix}"

    def clean(self) -> None:
        super().clean()
        if self.exact_path and not self.exact_path.startswith("/"):
            raise ValidationError({"exact_path": "Путь должен начинаться с /."})
        if self.schema_json_ld:
            try:
                value = json.loads(self.schema_json_ld)
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValidationError({"schema_json_ld": "Введите корректный JSON."}) from exc
            if not isinstance(value, (dict, list)):
                raise ValidationError({"schema_json_ld": "JSON-LD должен быть объектом или массивом."})

    def save(self, *args, **kwargs):
        if self.exact_path:
            normalized = self.exact_path.strip()
            self.exact_path = "/" if normalized == "/" else f"/{normalized.strip('/')}/".replace("\\/", "/")
        super().save(*args, **kwargs)
