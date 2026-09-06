from __future__ import annotations

from typing import Any

from .models import Notification, NotificationPreference


CATEGORY_FIELD_BY_KIND = {
    Notification.Kind.PREDICTION_LIKE: "prediction_like",
    Notification.Kind.PREDICTION_FAVORITE: "prediction_favorite",
    Notification.Kind.COPYBETTING: "copybetting",
    Notification.Kind.NEW_FOLLOWER: "new_follower",
    Notification.Kind.PAID_SUBSCRIPTION: "paid_subscription",
    Notification.Kind.NEW_PREDICTION: "new_prediction",
    Notification.Kind.REQUESTED_MATCH_PREDICTION: "requested_match_prediction",
    Notification.Kind.MATCH_PREDICTION: "match_prediction",
    Notification.Kind.TOURNAMENT_STARTED: "tournament_started",
    Notification.Kind.TOURNAMENT_FINISHED: "tournament_finished",
    Notification.Kind.OWN_COUPON_SETTLED: "own_coupon_settled",
    Notification.Kind.FAVORITE_SETTLED: "favorite_settled",
    Notification.Kind.MATCH_REMINDER: "match_reminder",
    Notification.Kind.ACHIEVEMENT: "achievement",
}


def get_preferences(user) -> NotificationPreference:
    preferences, _ = NotificationPreference.objects.get_or_create(user=user)
    return preferences


def category_enabled(preferences: NotificationPreference, kind: str) -> bool:
    field = CATEGORY_FIELD_BY_KIND.get(kind)
    if not field:
        return False
    return bool(getattr(preferences, field, False))


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
