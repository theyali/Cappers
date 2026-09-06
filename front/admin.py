from django.contrib import admin

from .models import Article, StaticPage, WikiTerm, WikiVideo


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ("title", "is_published", "created_at", "updated_at")
    list_filter = ("is_published", "created_at")
    search_fields = ("title", "description", "content")
    prepopulated_fields = {"slug": ("title",)}
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("Основное", {"fields": ("title", "slug", "description", "image", "is_published")}),
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


@admin.register(WikiVideo)
class WikiVideoAdmin(admin.ModelAdmin):
    list_display = ("title", "section", "is_published", "sort_order", "updated_at")
    list_display_links = ("title",)
    list_editable = ("is_published", "sort_order")
    list_filter = ("is_published", "section")
    search_fields = ("title", "section", "description")
    ordering = ("section", "sort_order", "title")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("Видео", {"fields": ("title", "section", "description", "video", "preview_image")}),
        ("Публикация", {"fields": ("is_published", "sort_order")}),
        ("Служебное", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )


@admin.register(WikiTerm)
class WikiTermAdmin(admin.ModelAdmin):
    list_display = ("term", "section", "is_published", "sort_order", "updated_at")
    list_display_links = ("term",)
    list_editable = ("is_published", "sort_order")
    list_filter = ("is_published", "section")
    search_fields = ("term", "section", "description")
    ordering = ("section", "sort_order", "term")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("Термин", {"fields": ("term", "section", "description")}),
        ("Публикация", {"fields": ("is_published", "sort_order")}),
        ("Служебное", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )
