from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    AnalystFollow,
    AnalystProfile,
    CapperMonthlyStat,
    CapperReferralVisit,
    MatchPredictionRequest,
    User,
)


@admin.register(User)
class CabinetUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Профиль", {"fields": ("role",)}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Профиль", {"fields": ("role",)}),
    )
    list_display = ("username", "email", "role", "is_staff", "is_active")
    list_filter = ("role", "is_staff", "is_active")


@admin.register(AnalystProfile)
class AnalystProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "display_name",
        "referral_code",
        "specialization",
        "telegram_channel",
        "telegram_account",
        "is_verified",
        "is_vip",
        "is_recommended",
        "is_public",
        "onboarding_completed_at",
        "created_at",
    )
    list_editable = ("is_verified", "is_vip", "is_recommended", "is_public")
    list_filter = (
        "is_verified",
        "is_vip",
        "is_recommended",
        "is_public",
        "created_at",
        "onboarding_completed_at",
    )
    search_fields = (
        "user__username",
        "user__email",
        "display_name",
        "referral_code",
        "specialization",
        "favorite_sports",
        "favorite_leagues",
        "telegram_channel",
        "telegram_account",
        "tiktok",
        "facebook",
    )
    autocomplete_fields = ("user",)
    readonly_fields = ("referral_code", "onboarding_completed_at", "created_at", "updated_at")
    fieldsets = (
        (
            "Эксперт",
            {
                "fields": (
                    "user",
                    "display_name",
                    "avatar",
                    "specialization",
                    "bio",
                    "favorite_sports",
                    "favorite_leagues",
                )
            },
        ),
        (
            "Социальные сети",
            {
                "fields": (
                    "telegram_channel",
                    "telegram_account",
                    "instagram",
                    "threads",
                    "youtube",
                    "tiktok",
                    "facebook",
                )
            },
        ),
        (
            "Статус",
            {
                "fields": (
                    "is_verified",
                    "is_vip",
                    "is_recommended",
                    "is_public",
                    "onboarding_completed_at",
                )
            },
        ),
        ("Системная информация", {"fields": ("referral_code", "created_at", "updated_at")}),
    )


@admin.register(AnalystFollow)
class AnalystFollowAdmin(admin.ModelAdmin):
    list_display = ("follower", "analyst", "created_at")
    search_fields = ("follower__username", "analyst__username")
    autocomplete_fields = ("follower", "analyst")
    readonly_fields = ("created_at",)


@admin.register(CapperReferralVisit)
class CapperReferralVisitAdmin(admin.ModelAdmin):
    list_display = (
        "analyst",
        "visitor",
        "visits_count",
        "first_seen_at",
        "last_seen_at",
        "subscribed_at",
    )
    list_filter = ("first_seen_at", "subscribed_at")
    search_fields = ("analyst__username", "visitor__username", "session_key")
    autocomplete_fields = ("analyst", "visitor")
    readonly_fields = (
        "analyst",
        "visitor",
        "session_key",
        "visits_count",
        "first_seen_at",
        "last_seen_at",
        "subscribed_at",
    )


@admin.register(MatchPredictionRequest)
class MatchPredictionRequestAdmin(admin.ModelAdmin):
    list_display = ("user", "match", "created_at")
    list_filter = ("created_at",)
    search_fields = (
        "user__username",
        "match__home_team__name",
        "match__home_team__name_ru",
        "match__away_team__name",
        "match__away_team__name_ru",
    )
    autocomplete_fields = ("user", "match")
    readonly_fields = ("created_at",)


@admin.register(CapperMonthlyStat)
class CapperMonthlyStatAdmin(admin.ModelAdmin):
    list_display = (
        "analyst",
        "month",
        "bets_count",
        "wins_count",
        "losses_count",
        "refunds_count",
        "flat_profit_percent",
        "roi",
        "avg_coefficient",
        "hit_rate",
        "calculated_at",
    )
    list_filter = ("month",)
    search_fields = ("analyst__username", "analyst__email")
    autocomplete_fields = ("analyst",)
    readonly_fields = (
        "analyst",
        "month",
        "bets_count",
        "wins_count",
        "losses_count",
        "refunds_count",
        "total_stake",
        "total_profit",
        "flat_profit_percent",
        "roi",
        "avg_coefficient",
        "hit_rate",
        "calculated_at",
    )
