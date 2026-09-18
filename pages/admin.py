from django.contrib import admin

from .models import (
    AdvBanner,
    HelpAccordionItem,
    HelpBlock,
    PagePromoBanner,
    PageSEO,
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
    fields = ("sort_order", "placement", "banner")
    ordering = ("placement", "sort_order", "id")
    autocomplete_fields = ("banner",)


@admin.register(HelpBlock)
class HelpBlockAdmin(admin.ModelAdmin):
    list_display = ("title", "key", "is_active", "updated_at")
    list_filter = ("is_active",)
    list_editable = ("is_active",)
    search_fields = ("title", "key", "items__title", "items__content")
    readonly_fields = ("updated_at",)
    ordering = ("title", "key")
    inlines = (HelpAccordionItemInline,)


@admin.register(PageSEO)
class PageSEOAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "route_name",
        "exact_path",
        "meta_title",
        "layout_columns",
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
    filter_horizontal = ("adv_banners",)
    inlines = (PagePromoBannerInline,)
    fieldsets = (
        (
            "Страница",
            {
                "fields": (
                    "name",
                    "route_name",
                    "exact_path",
                    "layout_columns",
                    "is_active",
                ),
                "description": (
                    "Для /articles/ используйте route_name='front:articles'. "
                    "Пустой exact_path действует на весь view; exact_path='/articles/' "
                    "имеет приоритет только для этого URL."
                ),
            },
        ),
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
