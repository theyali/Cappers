from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    AnalystFollow,
    AnalystPaidPlan,
    AnalystPaidSubscription,
    AnalystProfile,
    CapperMonthlyStat,
    MatchPredictionRequest,
    ReferralVisit,
    User,
)


@admin.register(User)
class CabinetUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Профиль", {"fields": ("role", "referral_code")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ("Профиль", {"fields": ("role",)}),
    )
    list_display = ("username", "email", "role", "referral_code", "is_staff", "is_active")
    list_filter = ("role", "is_staff", "is_active")
    readonly_fields = (*UserAdmin.readonly_fields, "referral_code")
    search_fields = (*UserAdmin.search_fields, "referral_code")


@admin.register(AnalystProfile)
class AnalystProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "display_name",
        "specialization",
        "telegram_channel",
        "telegram_account",
        "x",
        "is_verified",
        "verification_requested_at",
        "is_vip",
        "is_recommended",
        "trust_index",
        "trust_index_updated_at",
        "paid_predictions_enabled",
        "paid_predictions_price",
        "is_public",
        "onboarding_completed_at",
        "created_at",
    )
    list_editable = ("is_verified", "is_vip", "is_recommended", "paid_predictions_enabled", "is_public")
    list_filter = (
        "is_verified",
        "verification_requested_at",
        "is_vip",
        "is_recommended",
        "trust_index",
        "paid_predictions_enabled",
        "is_public",
        "created_at",
        "onboarding_completed_at",
    )
    search_fields = (
        "user__username",
        "user__email",
        "display_name",
        "specialization",
        "favorite_sports",
        "favorite_leagues",
        "telegram_channel",
        "telegram_account",
        "tiktok",
        "facebook",
        "x",
    )
    autocomplete_fields = ("user",)
    readonly_fields = (
        "trust_index",
        "trust_index_updated_at",
        "onboarding_completed_at",
        "created_at",
        "updated_at",
    )
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
                    "x",
                )
            },
        ),
        (
            "Статус",
            {
                "fields": (
                    "is_verified",
                    "verification_requested_at",
                    "is_vip",
                    "is_recommended",
                    "trust_index",
                    "trust_index_updated_at",
                    "paid_predictions_enabled",
                    "paid_predictions_price",
                    "is_public",
                    "onboarding_completed_at",
                )
            },
        ),
        (
            "Системная информация",
            {"fields": ("created_at", "updated_at")},
        ),
    )


@admin.register(AnalystFollow)
class AnalystFollowAdmin(admin.ModelAdmin):
    list_display = ("follower", "analyst", "created_at")
    search_fields = ("follower__username", "analyst__username")
    autocomplete_fields = ("follower", "analyst")
    readonly_fields = ("created_at",)


@admin.register(AnalystPaidPlan)
class AnalystPaidPlanAdmin(admin.ModelAdmin):
    list_display = (
        "analyst",
        "title",
        "duration_days",
        "price",
        "is_active",
        "order",
        "updated_at",
    )
    list_editable = ("price", "is_active", "order")
    list_filter = ("is_active", "duration_days", "created_at")
    search_fields = ("analyst__username", "analyst__email", "title")
    autocomplete_fields = ("analyst",)
    readonly_fields = ("created_at", "updated_at")
    ordering = ("analyst", "order", "duration_days", "id")


@admin.register(AnalystPaidSubscription)
class AnalystPaidSubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "subscriber",
        "analyst",
        "plan",
        "price",
        "duration_days",
        "starts_at",
        "expires_at",
        "is_active",
    )
    list_filter = ("starts_at", "expires_at")
    search_fields = ("subscriber__username", "analyst__username")
    autocomplete_fields = ("subscriber", "analyst", "plan")
    readonly_fields = ("created_at", "updated_at")


@admin.register(ReferralVisit)
class ReferralVisitAdmin(admin.ModelAdmin):
    list_display = (
        "referrer",
        "visitor",
        "visits_count",
        "first_seen_at",
        "last_seen_at",
        "registered_at",
        "subscribed_at",
    )
    list_filter = ("first_seen_at", "registered_at", "subscribed_at")
    search_fields = ("referrer__username", "visitor__username", "session_key")
    autocomplete_fields = ("referrer", "visitor")
    readonly_fields = (
        "referrer",
        "visitor",
        "session_key",
        "visits_count",
        "first_seen_at",
        "last_seen_at",
        "registered_at",
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


from . import roulette_admin  # noqa: E402,F401
from . import roulette_history_admin  # noqa: E402,F401
from . import roulette_rewards_admin  # noqa: E402,F401
from . import roulette_state_admin  # noqa: E402,F401
