from django.contrib import admin
from django.utils.html import format_html

from .models import Achievement, AchievementCategory


@admin.register(AchievementCategory)
class AchievementCategoryAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "sort_order", "is_active")
    list_editable = ("sort_order", "is_active")
    search_fields = ("title", "slug")
    prepopulated_fields = {"slug": ("title",)}
    ordering = ("sort_order", "title")


@admin.register(Achievement)
class AchievementAdmin(admin.ModelAdmin):
    list_display = (
        "icon_preview",
        "title",
        "key",
        "category",
        "audience",
        "metric",
        "target_value",
        "is_active",
        "sort_order",
    )
    list_filter = ("is_active", "audience", "metric", "category")
    list_editable = ("is_active", "sort_order")
    search_fields = ("title", "key", "description")
    autocomplete_fields = ("category",)
    readonly_fields = ("icon_preview", "created_at", "updated_at")
    fieldsets = (
        (
            "Основное",
            {
                "fields": (
                    "category",
                    "key",
                    "title",
                    "description",
                    "short_description",
                )
            },
        ),
        (
            "Иконка",
            {
                "fields": (
                    "icon",
                    "fallback_static_icon",
                    "icon_preview",
                )
            },
        ),
        (
            "Условие",
            {
                "fields": (
                    "audience",
                    "metric",
                    "condition_operator",
                    "target_value",
                )
            },
        ),
        (
            "Награды",
            {
                "fields": (
                    "coins_reward",
                    "xp_reward",
                )
            },
        ),
        (
            "Показы",
            {
                "fields": (
                    "is_active",
                    "is_secret",
                    "show_progress",
                    "sort_order",
                )
            },
        ),
        (
            "Система",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    @admin.display(description="Иконка")
    def icon_preview(self, obj):
        if obj.icon:
            return format_html(
                '<img src="{}" style="width:32px;height:32px;object-fit:contain">',
                obj.icon.url,
            )
        if obj.fallback_static_icon:
            return obj.fallback_static_icon
        return "—"
