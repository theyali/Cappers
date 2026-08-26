from django.contrib import admin

from .models import PageSEO


@admin.register(PageSEO)
class PageSEOAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "route_name",
        "exact_path",
        "robots",
        "is_active",
        "updated_at",
    )
    list_filter = ("is_active", "robots", "og_type", "twitter_card")
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
