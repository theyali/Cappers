from django.contrib import admin

from .models import Bookmaker, WebsiteSettings


@admin.register(Bookmaker)
class BookmakerAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "show_on_home",
        "home_order",
        "bonus_text",
        "exclusive",
        "order",
    )
    list_editable = ("show_on_home", "home_order", "exclusive", "order")
    list_filter = ("show_on_home", "exclusive")
    search_fields = ("name", "bonus_text", "description")
    ordering = ("order", "id")


@admin.register(WebsiteSettings)
class WebsiteSettingsAdmin(admin.ModelAdmin):
    list_display = ("site_name", "home_about_enabled", "fixed_tg_enable", "updated_at")
    readonly_fields = ("updated_at",)
    fieldsets = (
        (
            "Основное",
            {
                "fields": ("site_name",),
            },
        ),
        (
            "Telegram-баннер",
            {
                "fields": (
                    "fixed_tg_enable",
                    "fixed_tg_link",
                    "fixed_tg_title",
                ),
            },
        ),
        (
            "Букмекеры",
            {
                "fields": (
                    "match_bookmaker",
                    "prediction_bookmaker",
                ),
                "description": "Отдельный букмекер для коэффициентов матчей и отдельный — для карточек прогнозов.",
            },
        ),
        (
            "Главная страница — О нас",
            {
                "fields": (
                    "home_about_enabled",
                    "home_about_eyebrow",
                    "home_about_title",
                    "home_about_intro",
                    "home_about_text",
                ),
            },
        ),
        (
            "Главная страница — SEO и смысловые карточки",
            {
                "fields": (
                    "home_about_seo_title",
                    "home_about_seo_text",
                    "home_about_fact_1_title",
                    "home_about_fact_1_text",
                    "home_about_fact_2_title",
                    "home_about_fact_2_text",
                    "home_about_fact_3_title",
                    "home_about_fact_3_text",
                ),
            },
        ),
        (
            "Система",
            {
                "fields": ("updated_at",),
            },
        ),
    )

    def has_add_permission(self, request):
        return not WebsiteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
