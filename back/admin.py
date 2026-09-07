from django.contrib import admin

from .models import Bonus, Bookmaker, FooterButton, FooterLink, FooterLinkGroup, WebsiteSettings


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


@admin.register(Bonus)
class BonusAdmin(admin.ModelAdmin):
    list_display = (
        "bookmaker",
        "short_description",
        "promocode",
        "order",
    )
    list_editable = ("order",)
    list_filter = ("bookmaker",)
    search_fields = ("bookmaker__name", "short_description", "promocode")
    ordering = ("order", "id")


class FooterLinkInline(admin.TabularInline):
    model = FooterLink
    extra = 1
    fields = ("title", "url", "order", "is_active")


@admin.register(FooterLinkGroup)
class FooterLinkGroupAdmin(admin.ModelAdmin):
    list_display = ("title", "order", "is_active")
    list_editable = ("order", "is_active")
    search_fields = ("title",)
    ordering = ("order", "id")
    inlines = (FooterLinkInline,)


@admin.register(FooterButton)
class FooterButtonAdmin(admin.ModelAdmin):
    list_display = ("title", "kind", "subtitle", "order", "is_active")
    list_editable = ("order", "is_active")
    list_filter = ("kind", "is_active")
    search_fields = ("title", "subtitle", "url")
    ordering = ("kind", "order", "id")


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
            "Футер",
            {
                "fields": (
                    "footer_description",
                    "footer_age_label",
                    "footer_responsible_text",
                    "footer_support_title",
                    "footer_support_phone",
                    "footer_support_email",
                    "footer_legal_text",
                    "footer_copyright_text",
                    "footer_disclaimer_text",
                    "footer_address_text",
                ),
                "description": "Группы ссылок и кнопки футера редактируются отдельными разделами «Футер — группы ссылок» и «Футер — кнопки и логотипы».",
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
            "Реферальные начисления",
            {
                "fields": (
                    "referral_subscription_percent",
                    "referral_tournament_percent",
                    "referral_balance_topup_percent",
                ),
                "description": "Процент начисляется рефереру только если реферер является каппером.",
            },
        ),
        (
            "Комиссия площадки по тарифам",
            {
                "fields": (
                    "platform_fee_1_day_percent",
                    "platform_fee_7_days_percent",
                    "platform_fee_30_days_percent",
                    "platform_fee_90_days_percent",
                    "platform_fee_180_days_percent",
                ),
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
