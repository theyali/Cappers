from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import AnalystFollow, AnalystProfile, CapperReferralVisit, User


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
        "specialization",
        "telegram_channel",
        "telegram_account",
        "is_verified",
        "is_public",
        "onboarding_completed_at",
        "created_at",
    )
    list_editable = ("is_verified", "is_public")
    list_filter = ("is_verified", "is_public", "created_at", "onboarding_completed_at")
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
    )
    autocomplete_fields = ("user",)
    readonly_fields = ("onboarding_completed_at", "created_at", "updated_at")
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
        ("Статус", {"fields": ("is_verified", "is_public", "onboarding_completed_at")}),
        ("Системная информация", {"fields": ("created_at", "updated_at")}),
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
