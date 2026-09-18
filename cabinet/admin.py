from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    AnalystFollow,
    AnalystPaidPlan,
    AnalystPaidSubscription,
    AnalystProfile,
    BonusEvent,
    CapperMonthlyStat,
    DailyTask,
    MatchPredictionRequest,
    ReferralVisit,
    StreakReward,
    User,
    UserDailyStreak,
    UserDailyTaskProgress,
    UserVipSubscription,
    UserXpState,
    VipPlan,
    XpLevel,
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
        "vip_activated_at",
        "is_recommended",
        "trust_index",
        "trust_index_updated_at",
        "paid_predictions_enabled",
        "paid_predictions_price",
        "is_public",
        "onboarding_completed_at",
        "created_at",
    )
    list_editable = ("is_verified", "is_recommended", "paid_predictions_enabled", "is_public")
    list_filter = (
        "is_verified",
        "verification_requested_at",
        "is_vip",
        "vip_activated_at",
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
        "is_vip",
        "vip_activated_at",
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
            "Legacy VIP — только для проверки миграции",
            {"fields": ("is_vip", "vip_activated_at")},
        ),
        (
            "Системная информация",
            {"fields": ("created_at", "updated_at")},
        ),
    )


@admin.register(VipPlan)
class VipPlanAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "duration_days",
        "price_coins",
        "is_active",
        "order",
        "updated_at",
    )
    list_editable = ("price_coins", "is_active", "order")
    list_filter = ("is_active", "duration_days")
    search_fields = ("title",)
    ordering = ("order", "duration_days", "id")
    readonly_fields = ("created_at", "updated_at")


@admin.register(UserVipSubscription)
class UserVipSubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "plan",
        "source",
        "starts_at",
        "ends_at",
        "duration_days",
        "is_active",
    )
    list_filter = ("source", "is_active", "plan", "starts_at", "ends_at")
    search_fields = ("user__username", "user__email", "plan__title")
    autocomplete_fields = ("user", "plan")
    list_select_related = ("user", "plan")
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "starts_at"


@admin.register(DailyTask)
class DailyTaskAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "audience",
        "task_type",
        "target_value",
        "reward_xp",
        "reward_coins",
        "reward_spins",
        "is_active",
        "order",
    )
    list_filter = ("audience", "task_type", "is_active")
    search_fields = ("title", "description")
    ordering = ("order", "id")


@admin.register(XpLevel)
class XpLevelAdmin(admin.ModelAdmin):
    list_display = (
        "level",
        "title",
        "required_xp",
        "reward_coins",
        "reward_spins",
        "is_active",
        "order",
    )
    list_filter = ("is_active",)
    search_fields = ("title",)
    ordering = ("order", "level", "id")


@admin.register(StreakReward)
class StreakRewardAdmin(admin.ModelAdmin):
    list_display = (
        "day_number",
        "title",
        "reward_xp",
        "reward_coins",
        "reward_spins",
        "is_active",
    )
    list_filter = ("is_active",)
    search_fields = ("title",)
    ordering = ("day_number", "id")


@admin.register(UserDailyTaskProgress)
class UserDailyTaskProgressAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "task",
        "progress_date",
        "current_value",
        "is_completed",
        "completed_at",
        "reward_claimed_at",
    )
    list_filter = ("is_completed", "progress_date", "task__audience", "task__task_type")
    search_fields = ("user__username", "user__email", "task__title")
    autocomplete_fields = ("user", "task")
    list_select_related = ("user", "task")
    readonly_fields = (
        "user",
        "task",
        "progress_date",
        "current_value",
        "is_completed",
        "completed_at",
        "reward_claimed_at",
    )
    ordering = ("-progress_date", "-id")
    date_hierarchy = "progress_date"

    def has_add_permission(self, request):
        return False


@admin.register(UserXpState)
class UserXpStateAdmin(admin.ModelAdmin):
    list_display = ("user", "level", "xp", "created_at", "updated_at")
    search_fields = ("user__username", "user__email")
    autocomplete_fields = ("user",)
    list_select_related = ("user",)
    readonly_fields = ("user", "level", "xp", "created_at", "updated_at")
    ordering = ("-xp", "id")

    def has_add_permission(self, request):
        return False


@admin.register(UserDailyStreak)
class UserDailyStreakAdmin(admin.ModelAdmin):
    list_display = ("user", "current_days", "best_days", "last_seen_date", "updated_at")
    list_filter = ("last_seen_date",)
    search_fields = ("user__username", "user__email")
    autocomplete_fields = ("user",)
    list_select_related = ("user",)
    readonly_fields = ("user", "current_days", "best_days", "last_seen_date", "updated_at")
    ordering = ("-current_days", "-best_days", "id")
    date_hierarchy = "last_seen_date"

    def has_add_permission(self, request):
        return False


@admin.register(BonusEvent)
class BonusEventAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "event_type",
        "title",
        "xp_delta",
        "coin_delta",
        "spin_delta",
        "related_model",
        "related_id",
        "created_at",
    )
    list_filter = ("event_type", "created_at")
    search_fields = ("user__username", "user__email", "title", "description")
    autocomplete_fields = ("user",)
    list_select_related = ("user",)
    readonly_fields = (
        "user",
        "event_type",
        "title",
        "description",
        "xp_delta",
        "coin_delta",
        "spin_delta",
        "related_model",
        "related_id",
        "created_at",
    )
    ordering = ("-created_at", "-id")
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False


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


from .roulette import admin as roulette_admin  # noqa: E402,F401
from .roulette import history_admin as roulette_history_admin  # noqa: E402,F401
from .roulette import rewards_admin as roulette_rewards_admin  # noqa: E402,F401
from .roulette import state_admin as roulette_state_admin  # noqa: E402,F401
