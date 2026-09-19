from django.contrib import admin

from .forms import AdminNotificationCampaignForm
from .models import (
    AchievementState,
    AdminNotificationCampaign,
    CouponEventState,
    MatchWatch,
    Notification,
    NotificationPreference,
    TelegramAccount,
)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("recipient", "kind", "title", "is_read", "show_in_app", "created_at")
    list_filter = ("kind", "is_read", "show_in_app", "created_at")
    search_fields = ("recipient__username", "title", "message", "event_key")
    readonly_fields = (
        "event_key",
        "created_at",
        "read_at",
        "email_processed_at",
        "email_sent_at",
        "telegram_processed_at",
        "telegram_sent_at",
    )


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ("user", "in_app_enabled", "email_enabled", "telegram_enabled", "updated_at")
    search_fields = ("user__username", "user__email", "telegram_chat_id")


@admin.register(TelegramAccount)
class TelegramAccountAdmin(admin.ModelAdmin):
    list_display = ("user", "username", "chat_id", "connected_at", "last_seen_at")
    search_fields = ("user__username", "user__email", "username", "chat_id")
    readonly_fields = ("connected_at", "last_seen_at")


@admin.register(MatchWatch)
class MatchWatchAdmin(admin.ModelAdmin):
    list_display = ("user", "match", "created_at")
    search_fields = ("user__username", "match__home_team__name", "match__away_team__name")


@admin.register(AchievementState)
class AchievementStateAdmin(admin.ModelAdmin):
    list_display = ("user", "updated_at")
    search_fields = ("user__username",)


@admin.register(CouponEventState)
class CouponEventStateAdmin(admin.ModelAdmin):
    list_display = ("coupon", "published_dispatched_at", "settled_state", "settled_dispatched_at", "updated_at")
    search_fields = ("coupon__id", "coupon__author__username")
    readonly_fields = ("published_dispatched_at", "settled_dispatched_at", "updated_at")


@admin.register(AdminNotificationCampaign)
class AdminNotificationCampaignAdmin(admin.ModelAdmin):
    form = AdminNotificationCampaignForm
    list_display = (
        "title",
        "audience",
        "tournament",
        "recipients_count",
        "sent_at",
        "created_by",
        "created_at",
    )
    list_filter = ("audience", "sent_at", "created_at")
    search_fields = ("title", "message", "url", "created_by__username")
    autocomplete_fields = ("tournament",)
    readonly_fields = (
        "created_by",
        "created_at",
        "sent_at",
        "recipients_count",
    )
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "audience",
                    "title",
                    "message",
                    "url",
                    "image",
                )
            },
        ),
        (
            "Условия аудитории",
            {
                "fields": (
                    "inactive_days",
                    "tournament",
                )
            },
        ),
        (
            "Системные поля",
            {
                "fields": (
                    "created_by",
                    "created_at",
                    "sent_at",
                    "recipients_count",
                )
            },
        ),
    )

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
