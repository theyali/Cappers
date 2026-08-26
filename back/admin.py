from django.contrib import admin

from .models import Bookmaker, WebsiteSettings


@admin.register(Bookmaker)
class BookmakerAdmin(admin.ModelAdmin):
    list_display = ("name", "bonus_text", "exclusive", "order")
    list_editable = ("exclusive", "order")
    list_filter = ("exclusive",)
    search_fields = ("name", "bonus_text")
    ordering = ("order", "id")


@admin.register(WebsiteSettings)
class WebsiteSettingsAdmin(admin.ModelAdmin):
    list_display = ("site_name", "fixed_tg_enable", "fixed_tg_link", "updated_at")
    fields = (
        "site_name",
        "fixed_tg_enable",
        "fixed_tg_link",
        "fixed_tg_title",
        "updated_at",
    )
    readonly_fields = ("updated_at",)

    def has_add_permission(self, request):
        return not WebsiteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
