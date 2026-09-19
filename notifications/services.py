from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.urls import reverse
from django.utils import timezone

from .models import (
    AdminNotificationCampaign,
    Notification,
    NotificationPreference,
)


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
    Notification.Kind.BONUS_DAILY_TASK: "bonus_daily_task",
    Notification.Kind.BONUS_STREAK: "bonus_streak",
    Notification.Kind.BONUS_LEVEL: "bonus_level",
    Notification.Kind.BONUS_ROULETTE: "bonus_roulette",
    Notification.Kind.BONUS_REFERRAL: "bonus_referral",
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


def create_daily_task_completed_notification(
    *,
    recipient,
    task,
    progress_date,
) -> Notification | None:
    return create_notification(
        recipient=recipient,
        kind=Notification.Kind.BONUS_DAILY_TASK,
        title="Задание выполнено",
        message=task.title,
        url=reverse("cabinet:bonus_tasks"),
        event_key=(
            f"daily-task-completed:{recipient.pk}:{task.pk}:{progress_date}"
        ),
        meta={
            "daily_task_id": task.pk,
            "progress_date": str(progress_date),
        },
    )



def campaign_recipients_queryset(campaign):
    User = get_user_model()
    recipients = User.objects.filter(is_active=True)

    if campaign.audience == AdminNotificationCampaign.Audience.ALL_USERS:
        return recipients

    if campaign.audience == AdminNotificationCampaign.Audience.VIP_USERS:
        from cabinet.vip import active_vip_subscriptions

        active_vip = active_vip_subscriptions().filter(
            user_id=OuterRef("pk")
        )
        return recipients.annotate(
            _campaign_has_active_vip=Exists(active_vip)
        ).filter(_campaign_has_active_vip=True)

    if campaign.audience == AdminNotificationCampaign.Audience.READERS:
        return recipients.filter(role=User.Role.READER)

    if campaign.audience == AdminNotificationCampaign.Audience.CAPPERS:
        return recipients.filter(role=User.Role.ANALYST)

    if (
        campaign.audience
        == AdminNotificationCampaign.Audience.READERS_AND_CAPPERS
    ):
        return recipients.filter(
            role__in=(User.Role.READER, User.Role.ANALYST)
        )

    if (
        campaign.audience
        == AdminNotificationCampaign.Audience.TOURNAMENT_WINNERS
    ):
        return recipients.filter(
            tournament_participations__result__rank=1
        ).distinct()

    if (
        campaign.audience
        == AdminNotificationCampaign.Audience.TOURNAMENT_PARTICIPANTS
    ):
        if not campaign.tournament_id:
            return recipients.none()
        return recipients.filter(
            tournament_participations__tournament_id=campaign.tournament_id
        ).distinct()

    if campaign.audience == AdminNotificationCampaign.Audience.INACTIVE_USERS:
        if not campaign.inactive_days:
            return recipients.none()
        cutoff = timezone.now() - timedelta(days=campaign.inactive_days)
        return recipients.filter(last_login__lt=cutoff)

    return recipients.none()



@transaction.atomic
def send_admin_notification_campaign(campaign) -> tuple[int, bool]:
    campaign = (
        AdminNotificationCampaign.objects.select_for_update()
        .get(pk=campaign.pk)
    )
    if campaign.sent_at:
        return campaign.recipients_count, False

    recipient_ids = list(
        campaign_recipients_queryset(campaign).values_list("id", flat=True)
    )
    meta = {"campaign_id": campaign.pk}
    if campaign.image:
        meta["image_url"] = campaign.image.url

    notifications = [
        Notification(
            recipient_id=user_id,
            kind=Notification.Kind.ADMIN_CAMPAIGN,
            title=campaign.title,
            message=campaign.message,
            url=campaign.url,
            event_key=f"admin-campaign:{campaign.pk}:{user_id}",
            meta=meta,
        )
        for user_id in recipient_ids
    ]
    Notification.objects.bulk_create(notifications, batch_size=1000)

    campaign.sent_at = timezone.now()
    campaign.recipients_count = len(notifications)
    campaign.save(update_fields=["sent_at", "recipients_count"])
    return campaign.recipients_count, True
