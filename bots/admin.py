from django.contrib import admin

from bots.models import BotAccount, BotActionLog, BotExpertStrategy


@admin.register(BotAccount)
class BotAccountAdmin(admin.ModelAdmin):
    list_display = ("user", "kind", "persona", "is_active", "created_at")
    list_filter = ("kind", "is_active", "created_at")
    search_fields = ("user__username", "persona")
    autocomplete_fields = ("user",)


@admin.register(BotExpertStrategy)
class BotExpertStrategyAdmin(admin.ModelAdmin):
    list_display = (
        "bot",
        "cadence_days",
        "daily_predictions_min",
        "daily_predictions_max",
        "market_preference",
        "risk_profile",
        "next_run_at",
    )
    list_filter = ("cadence_days", "market_preference", "risk_profile")
    autocomplete_fields = ("bot",)


@admin.register(BotActionLog)
class BotActionLogAdmin(admin.ModelAdmin):
    list_display = ("bot", "action", "target", "created_at")
    list_filter = ("action", "created_at")
    search_fields = ("bot__user__username", "target")
    autocomplete_fields = ("bot",)
