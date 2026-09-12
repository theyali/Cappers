from django.contrib import admin

from .roulette_rewards import UserRouletteRewardState


@admin.register(UserRouletteRewardState)
class UserRouletteRewardStateAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "vip_until",
        "free_predictions",
        "rating_boost",
        "updated_at",
    )
    search_fields = ("user__username", "user__email")
    autocomplete_fields = ("user",)
    list_filter = ("vip_until", "updated_at")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("user_id",)
