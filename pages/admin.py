from django.contrib import admin

from .models import AdvBanner, PageSEO


@admin.register(AdvBanner)
class AdvBannerAdmin(admin.ModelAdmin):
    list_display = ("name", "size", "url")
    list_filter = ("size",)
    search_fields = ("name", "url")
    ordering = ("id",)


@admin.register(PageSEO)
class PageSEOAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "route_name",
        "exact_path",
        "adv_placement",
        "robots",
        "is_active",
        "updated_at",
    )
    list_filter = ("is_active", "adv_placement", "robots", "og_type", "twitter_card")
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
    fieldsets = (
        (
            "Страница",
            {
                "fields": (
                    "name",
                    "route_name",
                    "exact_path",
                    "is_active",
                )
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
