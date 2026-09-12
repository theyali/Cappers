from django.contrib import admin

from .roulette_state import UserRouletteState


@admin.register(UserRouletteState)
class UserRouletteStateAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "available_spins",
        "next_spin_at",
        "last_spin_at",
        "total_spins",
        "last_daily_grant_at",
        "updated_at",
    )
    list_editable = ("available_spins",)
    list_filter = ("next_spin_at", "last_spin_at", "last_daily_grant_at")
    search_fields = ("user__username", "user__email")
    autocomplete_fields = ("user",)
    ordering = ("user",)
    readonly_fields = (
        "last_spin_at",
        "total_spins",
        "last_daily_grant_at",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (
            "Пользователь",
            {"fields": ("user",)},
        ),
        (
            "Попытки",
            {
                "fields": (
                    "available_spins",
                    "next_spin_at",
                    "last_spin_at",
                    "total_spins",
                    "last_daily_grant_at",
                )
            },
        ),
        (
            "Системная информация",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )
