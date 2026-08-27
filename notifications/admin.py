from django.contrib import admin

from .models import (
    AchievementState,
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
