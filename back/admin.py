from django.contrib import admin

from .models import Bookmaker, SiteSettings


@admin.register(Bookmaker)
class BookmakerAdmin(admin.ModelAdmin):
    list_display = ("name", "bonus_text", "exclusive", "order")
    list_editable = ("exclusive", "order")
    list_filter = ("exclusive",)
    search_fields = ("name", "bonus_text")
    ordering = ("order", "id")


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    fields = ("telegram_bot_url",)

    def has_add_permission(self, request):
        return not SiteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
