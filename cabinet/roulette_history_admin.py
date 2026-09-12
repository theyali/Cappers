from django.contrib import admin

from .roulette_history import RouletteSpin


@admin.register(RouletteSpin)
class RouletteSpinAdmin(admin.ModelAdmin):
    list_display = (
        "operation_id",
        "user",
        "prize_title",
        "reward_type",
        "reward_value",
        "reward_status",
        "attempts_before",
        "attempts_after",
        "spun_at",
        "issued_at",
    )
    list_filter = (
        "reward_status",
        "reward_type",
        "spun_at",
        "issued_at",
    )
    search_fields = (
        "=operation_id",
        "user__username",
        "user__email",
        "prize_title",
        "reward_text",
    )
    autocomplete_fields = ("user", "prize")
    date_hierarchy = "spun_at"
    ordering = ("-spun_at", "-id")
    list_select_related = ("user", "prize")
    readonly_fields = (
        "operation_id",
        "user",
        "prize",
        "spun_at",
        "attempts_before",
        "attempts_after",
        "next_spin_at",
        "prize_title",
        "prize_short_text",
        "prize_icon",
        "prize_sector_order",
        "reward_type",
        "reward_value",
        "reward_text",
        "reward_status",
        "issued_at",
        "issue_error",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (
            "Операция",
            {
                "fields": (
                    "operation_id",
                    "user",
                    "spun_at",
                    "attempts_before",
                    "attempts_after",
                    "next_spin_at",
                )
            },
        ),
        (
            "Связанный приз",
            {"fields": ("prize",)},
        ),
        (
            "Snapshot приза",
            {
                "fields": (
                    "prize_title",
                    "prize_short_text",
                    "prize_icon",
                    "prize_sector_order",
                    "reward_type",
                    "reward_value",
                    "reward_text",
                )
            },
        ),
        (
            "Выдача награды",
            {
                "fields": (
                    "reward_status",
                    "issued_at",
                    "issue_error",
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

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
