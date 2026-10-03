from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Exists, F, OuterRef
from django.urls import reverse
from django.utils import timezone

from .models import (
    AdminNotificationCampaign,
    Notification,
    NotificationPreference,
    NotificationSectionState,
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


SECTION_BY_KIND = {
    Notification.Kind.PREDICTION_LIKE: NotificationSectionState.Section.PREDICTIONS,
    Notification.Kind.PREDICTION_FAVORITE: NotificationSectionState.Section.PREDICTIONS,
    Notification.Kind.OWN_COUPON_SETTLED: NotificationSectionState.Section.PREDICTIONS,
    Notification.Kind.COPYBETTING: NotificationSectionState.Section.COPYBETTING,
    Notification.Kind.NEW_FOLLOWER: NotificationSectionState.Section.FOLLOWERS,
    Notification.Kind.PAID_SUBSCRIPTION: NotificationSectionState.Section.EARNINGS,
    Notification.Kind.ACHIEVEMENT: NotificationSectionState.Section.ACHIEVEMENTS,
    Notification.Kind.BONUS_DAILY_TASK: NotificationSectionState.Section.BONUS_TASKS,
    Notification.Kind.BONUS_STREAK: NotificationSectionState.Section.BONUS_LEVELS,
    Notification.Kind.BONUS_LEVEL: NotificationSectionState.Section.BONUS_LEVELS,
    Notification.Kind.BONUS_ROULETTE: NotificationSectionState.Section.BONUSES,
    Notification.Kind.BONUS_REFERRAL: NotificationSectionState.Section.REFERRALS,
    Notification.Kind.NEW_PREDICTION: NotificationSectionState.Section.FOLLOWING,
    Notification.Kind.REQUESTED_MATCH_PREDICTION: NotificationSectionState.Section.FOLLOWING,
    Notification.Kind.FAVORITE_SETTLED: NotificationSectionState.Section.FOLLOWING,
    Notification.Kind.MATCH_PREDICTION: NotificationSectionState.Section.MATCHES,
    Notification.Kind.MATCH_REMINDER: NotificationSectionState.Section.MATCHES,
    Notification.Kind.TOURNAMENT_STARTED: NotificationSectionState.Section.TOURNAMENTS,
    Notification.Kind.TOURNAMENT_FINISHED: NotificationSectionState.Section.TOURNAMENTS,
}


def get_preferences(user) -> NotificationPreference:
    preferences, _ = NotificationPreference.objects.get_or_create(user=user)
    return preferences


def category_enabled(preferences: NotificationPreference, kind: str) -> bool:
    field = CATEGORY_FIELD_BY_KIND.get(kind)
    if not field:
        return False
    return bool(getattr(preferences, field, False))


def notification_section_for_kind(kind: str) -> str:
    return SECTION_BY_KIND.get(kind, "")


def increment_section_state(notification: Notification) -> None:
    if notification.is_read or not notification.show_in_app:
        return
    section = notification_section_for_kind(notification.kind)
    if not section:
        return

    updated = NotificationSectionState.objects.filter(
        user=notification.recipient,
        section=section,
    ).update(
        unread_count=F("unread_count") + 1,
        latest_notification=notification,
    )
    if updated:
        return

    try:
        NotificationSectionState.objects.create(
            user=notification.recipient,
            section=section,
            unread_count=1,
            latest_notification=notification,
        )
    except IntegrityError:
        NotificationSectionState.objects.filter(
            user=notification.recipient,
            section=section,
        ).update(
            unread_count=F("unread_count") + 1,
            latest_notification=notification,
        )


def decrement_section_state(notification: Notification) -> None:
    section = notification_section_for_kind(notification.kind)
    if not section:
        return

    NotificationSectionState.objects.filter(
        user=notification.recipient,
        section=section,
        unread_count__gt=0,
    ).update(unread_count=F("unread_count") - 1)


def notification_kinds_for_section(section: str) -> list[str]:
    return [
        kind
        for kind, target_section in SECTION_BY_KIND.items()
        if target_section == section
    ]


def refresh_section_state(user, section: str) -> int:
    kinds = notification_kinds_for_section(section)
    if not kinds:
        return 0

    unread_queryset = Notification.objects.filter(
        recipient=user,
        show_in_app=True,
        is_read=False,
        kind__in=kinds,
    )
    unread_count = unread_queryset.count()
    latest_notification = unread_queryset.order_by("-created_at", "-id").first()

    NotificationSectionState.objects.update_or_create(
        user=user,
        section=section,
        defaults={
            "unread_count": unread_count,
            "latest_notification": latest_notification,
        },
    )
    return unread_count


def clear_section_states(user) -> None:
    NotificationSectionState.objects.filter(user=user, unread_count__gt=0).update(
        unread_count=0,
        latest_notification=None,
    )


def section_badge_payload(user) -> dict[str, dict]:
    if not getattr(user, "is_authenticated", False):
        return {
            "badges": {},
            "counts": {},
        }

    rows = NotificationSectionState.objects.filter(
        user=user,
        unread_count__gt=0,
    ).values_list("section", "unread_count")
    counts = {section: count for section, count in rows}
    return {
        "badges": {section: True for section in counts},
        "counts": counts,
    }


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

    notification, created = Notification.objects.get_or_create(
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
    if created:
        increment_section_state(notification)
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
    in_app_preferences = {
        preference.user_id: preference.in_app_enabled
        for preference in NotificationPreference.objects.filter(user_id__in=recipient_ids)
    }
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
            show_in_app=in_app_preferences.get(user_id, True),
        )
        for user_id in recipient_ids
    ]
    Notification.objects.bulk_create(notifications, batch_size=1000)

    campaign.sent_at = timezone.now()
    campaign.recipients_count = len(notifications)
    campaign.save(update_fields=["sent_at", "recipients_count"])
    return campaign.recipients_count, True
