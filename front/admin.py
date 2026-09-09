from django.contrib import admin

from .models import (
    Article,
    ArticleCategory,
    StaticPage,
    WikiTerm,
    WikiTermSection,
    WikiVideo,
    WikiVideoSection,
)


@admin.register(ArticleCategory)
class ArticleCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "sort_order", "updated_at")
    list_display_links = ("name",)
    list_editable = ("is_active", "sort_order")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("Основное", {"fields": ("name", "slug", "is_active", "sort_order")}),
        ("Служебное", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "category",
        "reading_time_minutes",
        "is_main",
        "is_published",
        "created_at",
        "updated_at",
    )
    list_filter = ("is_main", "is_published", "category", "created_at")
    search_fields = ("title", "description", "content", "tags", "category__name")
    prepopulated_fields = {"slug": ("title",)}
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("Основное", {"fields": ("title", "slug", "category", "description", "image")}),
        ("Метаданные", {"fields": ("reading_time_minutes", "tags", "is_main", "is_published")}),
        ("Содержание", {"fields": ("content",)}),
        ("Служебное", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )


@admin.register(StaticPage)
class StaticPageAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "is_published", "show_in_footer", "footer_order", "updated_at")
    list_filter = ("is_published", "show_in_footer")
    search_fields = ("title", "content")
    prepopulated_fields = {"slug": ("title",)}
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("Основное", {"fields": ("title", "slug", "is_published", "show_in_footer", "footer_order")}),
        ("Содержание", {"fields": ("content",)}),
        ("Служебное", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )


@admin.register(WikiVideoSection)
class WikiVideoSectionAdmin(admin.ModelAdmin):
    list_display = ("name", "icon", "is_active", "sort_order")
    list_display_links = ("name",)
    list_editable = ("icon", "is_active", "sort_order")
    list_filter = ("is_active", "icon")
    search_fields = ("name",)
    ordering = ("sort_order", "name")


@admin.register(WikiVideo)
class WikiVideoAdmin(admin.ModelAdmin):
    list_display = ("title", "section", "duration", "is_published", "sort_order", "updated_at")
    list_display_links = ("title",)
    list_editable = ("is_published", "sort_order")
    list_filter = ("is_published", "section")
    search_fields = ("title", "section__name", "description")
    ordering = ("section__sort_order", "sort_order", "title")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("Видео", {"fields": ("title", "section", "description", "video", "preview_image", "duration")}),
        ("Публикация", {"fields": ("is_published", "sort_order")}),
        ("Служебное", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )


@admin.register(WikiTermSection)
class WikiTermSectionAdmin(admin.ModelAdmin):
    list_display = ("name", "icon", "accent", "is_active", "sort_order")
    list_display_links = ("name",)
    list_editable = ("icon", "accent", "is_active", "sort_order")
    list_filter = ("is_active", "icon", "accent")
    search_fields = ("name",)
    ordering = ("sort_order", "name")


@admin.register(WikiTerm)
class WikiTermAdmin(admin.ModelAdmin):
    list_display = ("term", "section", "icon", "is_published", "sort_order", "updated_at")
    list_display_links = ("term",)
    list_editable = ("icon", "is_published", "sort_order")
    list_filter = ("is_published", "section", "icon")
    search_fields = ("term", "section__name", "description")
    ordering = ("section__sort_order", "sort_order", "term")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("Термин", {"fields": ("term", "section", "icon", "description")}),
        ("Публикация", {"fields": ("is_published", "sort_order")}),
        ("Служебное", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )
