from django.contrib.contenttypes.fields import GenericRelation
from django.contrib.contenttypes.models import ContentType
from django.db import models

from .slugs import publication_slug


class PublicationContent(models.Model):
    """Optional content blocks shared by editorial articles, news and capper articles."""

    table_of_contents = models.TextField(
        "Содержание",
        blank=True,
        help_text="Заголовки H2/H3 из текста, по одному в строке. Пустое поле скрывает содержание.",
    )
    inline_image = models.ImageField(
        "Изображение в тексте", upload_to="publications/", blank=True
    )
    inline_image_caption = models.CharField(
        "Подпись изображения", max_length=500, blank=True
    )
    inline_image_after_paragraph = models.PositiveSmallIntegerField(
        "Изображение — после абзаца", default=2
    )
    pull_quote = models.TextField("Цитата", blank=True)
    quote_after_paragraph = models.PositiveSmallIntegerField(
        "Цитата — после абзаца", default=2
    )
    related_link_url = models.CharField(
        "Ссылка на другой материал",
        max_length=500,
        blank=True,
        help_text="Полный адрес или путь на сайте, например /articles/example/.",
    )
    related_link_title = models.CharField(
        "Заголовок связанного материала", max_length=220, blank=True
    )
    related_link_image = models.ImageField(
        "Изображение связанного материала", upload_to="publications/", blank=True
    )
    related_link_after_paragraph = models.PositiveSmallIntegerField(
        "Ссылка — после абзаца", default=2
    )
    summary = models.TextField("Краткий вывод («Коротко»)", blank=True)
    summary_after_paragraph = models.PositiveSmallIntegerField(
        "Вывод — после абзаца", default=4
    )
    featured_prediction = models.ForeignKey(
        "game.PredictionCoupon",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        verbose_name="Прогноз из материала",
    )
    prediction_after_paragraph = models.PositiveSmallIntegerField(
        "Прогноз — после абзаца", default=4
    )
    comments_enabled = models.BooleanField("Комментарии включены", default=True)
    views_count = models.PositiveIntegerField("Просмотры", default=0, editable=False)
    publication_reactions = GenericRelation("front.PublicationReaction")
    publication_comments = GenericRelation("cabinet.Comment")
    previous_slugs = GenericRelation("front.PublicationSlug")

    class Meta:
        abstract = True

    def clean(self):
        super().clean()
        from django.core.exceptions import ValidationError
        from urllib.parse import urlsplit

        if self.slug and self._meta.get_field("slug").unique:
            from front.models import PublicationSlug

            if (
                PublicationSlug.objects.filter(
                    content_type=ContentType.objects.get_for_model(self),
                    slug=self.slug,
                )
                .exclude(object_id=self.pk)
                .exists()
            ):
                raise ValidationError(
                    {
                        "slug": "Этот адрес сохранён за другим материалом. Укажите другой slug."
                    }
                )

        if self.related_link_url:
            value = self.related_link_url.strip()
            parsed = urlsplit(value)
            if not (
                (value.startswith("/") and not value.startswith("//"))
                or (parsed.scheme in {"http", "https"} and parsed.netloc)
            ):
                raise ValidationError(
                    {
                        "related_link_url": "Укажите адрес http(s) или путь на этом сайте."
                    }
                )
            self.related_link_url = value

    def save(self, *args, **kwargs):
        previous = (
            type(self).objects.filter(pk=self.pk).values("title", "slug").first()
            if self.pk
            else None
        )
        fields = kwargs.get("update_fields")
        title_changed = (
            previous
            and previous["title"] != self.title
            and (fields is None or "title" in fields)
        )
        slug_field = self._meta.get_field("slug")
        if not self.slug or (title_changed and self.slug == previous["slug"]):
            candidate = base = publication_slug(
                self.title, max_length=slug_field.max_length
            )
            if slug_field.unique:
                from front.models import PublicationSlug

                content_type = ContentType.objects.get_for_model(self)
                suffix = 1
                while (
                    type(self)
                    .objects.filter(slug=candidate)
                    .exclude(pk=self.pk)
                    .exists()
                    or PublicationSlug.objects.filter(
                        content_type=content_type, slug=candidate
                    )
                    .exclude(object_id=self.pk)
                    .exists()
                ):
                    suffix += 1
                    ending = f"-{suffix}"
                    candidate = base[: slug_field.max_length - len(ending)] + ending
            self.slug = candidate
            if fields is not None:
                kwargs["update_fields"] = set(fields) | {"slug"}
        result = super().save(*args, **kwargs)
        if (
            previous
            and previous["slug"]
            and previous["slug"] != self.slug
            and slug_field.unique
            and (
                kwargs.get("update_fields") is None or "slug" in kwargs["update_fields"]
            )
        ):
            from front.models import PublicationSlug

            PublicationSlug.objects.get_or_create(
                content_type=ContentType.objects.get_for_model(self),
                slug=previous["slug"],
                defaults={"object_id": self.pk},
            )
        return result
