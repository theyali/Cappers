from __future__ import annotations

from typing import Any

from .models import Notification, NotificationPreference


CATEGORY_FIELD_BY_KIND = {
    Notification.Kind.NEW_PREDICTION: "new_prediction",
    Notification.Kind.FAVORITE_SETTLED: "favorite_settled",
    Notification.Kind.MATCH_REMINDER: "match_reminder",
    Notification.Kind.ACHIEVEMENT: "achievement",
    Notification.Kind.MATCH_PREDICTION: "match_prediction",
}


def get_preferences(user) -> NotificationPreference:
    preferences, _ = NotificationPreference.objects.get_or_create(user=user)
    return preferences


def category_enabled(preferences: NotificationPreference, kind: str) -> bool:
    field = CATEGORY_FIELD_BY_KIND.get(kind)
    if not field:
        return True
    return bool(getattr(preferences, field, True))


def create_notification(
    *,
    recipient,
    kind: str,
    title: str,
    event_key: str,
    message: str = "",
    url: str = "",
    actor=None,
    meta: dict[str, Any] | None = None,
) -> Notification | None:
    preferences = get_preferences(recipient)
    if not category_enabled(preferences, kind):
        return None

    notification, _ = Notification.objects.get_or_create(
        event_key=event_key,
        defaults={
            "recipient": recipient,
            "actor": actor,
            "kind": kind,
            "title": title,
            "message": message,
            "url": url,
            "meta": meta or {},
            "show_in_app": preferences.in_app_enabled,
        },
    )
    return notification
