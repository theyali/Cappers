from django.contrib import admin

from .models import (
    AdvBanner,
    HelpAccordionItem,
    HelpBlock,
    PagePromoBanner,
    PageSEO,
    PageDocumentSection,
    PageDocumentCookie,
    PromoBanner,
)


@admin.register(AdvBanner)
class AdvBannerAdmin(admin.ModelAdmin):
    list_display = ("name", "size", "url")
    list_filter = ("size",)
    search_fields = ("name", "url")
    ordering = ("id",)


@admin.register(PromoBanner)
class PromoBannerAdmin(admin.ModelAdmin):
    list_display = ("name", "variant", "audience", "title", "button_label", "button_url", "is_active", "updated_at")
    list_filter = ("variant", "audience", "is_active")
    list_editable = ("is_active",)
    search_fields = ("name", "eyebrow", "title", "text", "button_label", "button_url")
    readonly_fields = ("updated_at",)
    ordering = ("name", "id")
    fieldsets = (
        (
            "Контент",
            {
                "description": (
                    "Для простого промо достаточно заполнить только изображение и ссылку. "
                    "Если заполнить текстовые поля, баннер будет работать в старом текстовом формате."
                ),
                "fields": (
                    "name",
                    "eyebrow",
                    "title",
                    "text",
                    "button_label",
                    "button_url",
                    "audience",
                    "is_active",
                ),
            },
        ),
        (
            "Изображения",
            {
                "fields": (
                    "image",
                    "mobile_image",
                    "variant",
                )
            },
        ),
        (
            "Цвета",
            {
                "fields": (
                    "title_color",
                    "text_color",
                    "button_color",
                    "button_text_color",
                )
            },
        ),
        (
            "Система",
            {
                "fields": ("updated_at",),
                "classes": ("collapse",),
            },
        ),
    )


class HelpAccordionItemInline(admin.StackedInline):
    model = HelpAccordionItem
    extra = 1
    fields = ("sort_order", "title", "content", "is_active")
    ordering = ("sort_order", "id")


class PagePromoBannerInline(admin.TabularInline):
    model = PagePromoBanner
    extra = 1
    fields = ("sort_order", "placement", "banner", "banner_audience", "banner_is_active")
    readonly_fields = ("banner_audience", "banner_is_active")
    ordering = ("placement", "sort_order", "id")
    autocomplete_fields = ("banner",)

    @admin.display(description="Аудитория баннера")
    def banner_audience(self, obj):
        if not obj.pk or not obj.banner_id:
            return "—"
        return obj.banner.get_audience_display()

    @admin.display(description="Активен")
    def banner_is_active(self, obj):
        if not obj.pk or not obj.banner_id:
            return "—"
        return "Да" if obj.banner.is_active else "Нет"


@admin.register(HelpBlock)
class HelpBlockAdmin(admin.ModelAdmin):
    list_display = ("title", "key", "is_active", "updated_at")
    list_filter = ("is_active",)
    list_editable = ("is_active",)
    search_fields = ("title", "key", "items__title", "items__content")
    readonly_fields = ("updated_at",)
    ordering = ("title", "key")
    inlines = (HelpAccordionItemInline,)


class PageDocumentSectionInline(admin.StackedInline):
    model = PageDocumentSection
    extra = 0
    fields = ("sort_order", "title", "anchor", "kind", "content", "is_active")


class PageDocumentCookieInline(admin.StackedInline):
    model = PageDocumentCookie
    extra = 0
    max_num = 4
    fields = ("sort_order", "category", "title", "description", "examples", "required_label")


@admin.register(PageSEO)
class PageSEOAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "route_name",
        "exact_path",
        "meta_title",
        "layout_columns",
        "home_top_experts_limit",
        "adv_placement",
        "robots",
        "is_active",
        "updated_at",
    )
    list_filter = (
        "is_active",
        "layout_columns",
        "adv_placement",
        "robots",
        "og_type",
        "twitter_card",
    )
    list_editable = ("is_active",)
    search_fields = (
        "name",
        "route_name",
        "exact_path",
        "meta_title",
        "meta_description",
        "meta_keywords",
    )
    ordering = ("route_name", "exact_path", "name")
    readonly_fields = ("updated_at",)
    filter_horizontal = ("adv_banners", "document_related_pages")
    inlines = (PagePromoBannerInline, PageDocumentSectionInline, PageDocumentCookieInline)
    fieldsets = (
        (
            "Страница",
            {
                "fields": (
                    "name",
                    "route_name",
                    "exact_path",
                    "layout_columns",
                    "home_top_experts_limit",
                    "is_active",
                ),
                "description": (
                    "Для /articles/ используйте route_name='front:articles'. "
                    "Пустой exact_path действует на весь view; exact_path='/articles/' "
                    "имеет приоритет только для этого URL."
                ),
            },
        ),
        ("Документ — оформление и содержание", {
            "fields": ("document_enabled", "document_title", "document_subtitle", "document_icon",
                       "document_updated_on", "document_revision", "document_pdf", "document_related_pages"),
            "description": "Разделы, таблицы и категории cookie редактируются ниже. Дизайн общий для всех документов.",
        }),
        ("Документ — поддержка", {
            "fields": ("document_support_title", "document_support_text", "document_support_button", "document_support_url"),
        }),
        ("Документ — подписи интерфейса", {"fields": ("document_labels",), "classes": ("collapse",)}),
        (
            "Реклама",
            {
                "fields": (
                    "adv_placement",
                    "adv_banners",
                )
            },
        ),
        (
            "Основное SEO",
            {
                "fields": (
                    "meta_title",
                    "meta_description",
                    "meta_keywords",
                    "canonical_url",
                    "robots",
                )
            },
        ),
        (
            "Open Graph / соцсети",
            {
                "fields": (
                    "og_title",
                    "og_description",
                    "og_image",
                    "og_type",
                    "twitter_card",
                )
            },
        ),
        (
            "Schema.org",
            {
                "fields": (
                    "schema_type",
                    "schema_json_ld",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Система",
            {
                "fields": ("updated_at",),
                "classes": ("collapse",),
            },
        ),
    )
