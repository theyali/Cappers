import json
import urllib.request
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from cabinet.achievements import build_achievement_overview
from cabinet.models import AnalystFollow, AnalystProfile, User
from front.models import PredictionFavorite
from game.models import Match, PredictionCoupon

from .models import AchievementState, CouponEventState, MatchWatch, Notification
from .services import create_notification, get_preferences


SETTLED_STATES = {
    PredictionCoupon.StateStatus.WIN,
    PredictionCoupon.StateStatus.LOSE,
    PredictionCoupon.StateStatus.REFUND,
}


def _expert_name(user) -> str:
    try:
        profile = user.analyst_profile
    except AnalystProfile.DoesNotExist:
        profile = None
    return (
        profile.display_name
        if profile and profile.display_name
        else user.get_full_name() or user.username
    )


def _match_name(match) -> str:
    return f"{match.home_team_name or 'Хозяева'} — {match.away_team_name or 'Гости'}"


def _new_prediction_events(coupon: PredictionCoupon) -> int:
    if coupon.published_status != PredictionCoupon.PublishedStatus.PUBLISHED:
        return 0

    created = 0
    author_name = _expert_name(coupon.author)
    url = reverse("front:prediction_detail", kwargs={"prediction_id": coupon.id})
    follower_rows = list(
        AnalystFollow.objects.filter(analyst_id=coupon.author_id)
        .select_related("follower")
    )
    follower_ids = {row.follower_id for row in follower_rows}

    for row in follower_rows:
        notification = create_notification(
            recipient=row.follower,
            actor=coupon.author,
            kind=Notification.Kind.NEW_PREDICTION,
            title=f"Новый прогноз от {author_name}",
            message="Каппер, на которого вы подписаны, опубликовал новый прогноз.",
            url=url,
            event_key=f"new-prediction:{row.follower_id}:{coupon.id}",
            meta={"coupon_id": coupon.id, "author_id": coupon.author_id},
        )
        created += int(notification is not None)

    positions = list(
        coupon.predictions.select_related(
            "match__home_team",
            "match__away_team",
        )
    )
    for position in positions:
        watchers = MatchWatch.objects.filter(match_id=position.match_id).select_related("user")
        for watch in watchers:
            if watch.user_id == coupon.author_id or watch.user_id in follower_ids:
                continue
            notification = create_notification(
                recipient=watch.user,
                actor=coupon.author,
                kind=Notification.Kind.MATCH_PREDICTION,
                title="На выбранный матч появился прогноз",
                message=f"{author_name} опубликовал прогноз на {_match_name(position.match)}.",
                url=url,
                event_key=f"match-prediction:{watch.user_id}:{coupon.id}:{position.match_id}",
                meta={
                    "coupon_id": coupon.id,
                    "match_id": position.match_id,
                    "author_id": coupon.author_id,
                },
            )
            created += int(notification is not None)
    return created


def _favorite_settlement_events(coupon: PredictionCoupon) -> int:
    if coupon.state_status not in SETTLED_STATES:
        return 0

    result_labels = {
        PredictionCoupon.StateStatus.WIN: "выиграл",
        PredictionCoupon.StateStatus.LOSE: "проиграл",
        PredictionCoupon.StateStatus.REFUND: "получил возврат",
    }
    created = 0
    url = reverse("front:prediction_detail", kwargs={"prediction_id": coupon.id})
    favorites = PredictionFavorite.objects.filter(prediction_id=coupon.id).select_related("user")
    for favorite in favorites:
        notification = create_notification(
            recipient=favorite.user,
            actor=coupon.author,
            kind=Notification.Kind.FAVORITE_SETTLED,
            title="Избранный прогноз рассчитан",
            message=f"Прогноз #{coupon.id} {result_labels[coupon.state_status]}.",
            url=url,
            event_key=f"favorite-settled:{favorite.user_id}:{coupon.id}:{coupon.state_status}",
            meta={"coupon_id": coupon.id, "state": coupon.state_status},
        )
        created += int(notification is not None)
    return created


@shared_task
def dispatch_recent_coupon_events() -> dict:
    now = timezone.now()
    cutoff = now - timedelta(hours=2)
    new_count = 0
    settled_count = 0

    published = (
        PredictionCoupon.objects.filter(
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            published_at__gte=cutoff,
        )
        .select_related("author", "author__analyst_profile")
        .prefetch_related("predictions__match__home_team", "predictions__match__away_team")
        .order_by("published_at", "id")
    )
    for coupon in published:
        state, _ = CouponEventState.objects.get_or_create(coupon=coupon)
        if state.published_dispatched_at:
            continue
        new_count += _new_prediction_events(coupon)
        state.published_dispatched_at = now
        state.save(update_fields=["published_dispatched_at", "updated_at"])

    settled = (
        PredictionCoupon.objects.filter(
            state_status__in=SETTLED_STATES,
            settled_at__gte=cutoff,
        )
        .select_related("author", "author__analyst_profile")
        .order_by("settled_at", "id")
    )
    for coupon in settled:
        state, _ = CouponEventState.objects.get_or_create(coupon=coupon)
        if state.settled_dispatched_at and state.settled_state == coupon.state_status:
            continue
        settled_count += _favorite_settlement_events(coupon)
        state.settled_state = coupon.state_status
        state.settled_dispatched_at = now
        state.save(update_fields=["settled_state", "settled_dispatched_at", "updated_at"])

    return {"new_prediction_events": new_count, "settlement_events": settled_count}


@shared_task
def notify_match_reminders() -> int:
    now = timezone.now()
    window_start = now + timedelta(minutes=55)
    window_end = now + timedelta(minutes=65)
    favorites = (
        PredictionFavorite.objects.filter(
            prediction__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            prediction__predictions__match__sync_scope=Match.SyncScope.PREMATCH,
            prediction__predictions__match__starts_at__gte=window_start,
            prediction__predictions__match__starts_at__lt=window_end,
        )
        .select_related("user", "prediction")
        .prefetch_related(
            "prediction__predictions__match__home_team",
            "prediction__predictions__match__away_team",
        )
        .distinct()
    )

    created = 0
    for favorite in favorites:
        for position in favorite.prediction.predictions.all():
            match = position.match
            if not match.starts_at or not (window_start <= match.starts_at < window_end):
                continue
            notification = create_notification(
                recipient=favorite.user,
                actor=favorite.prediction.author,
                kind=Notification.Kind.MATCH_REMINDER,
                title="Матч из избранного начнётся примерно через час",
                message=_match_name(match),
                url=match.get_absolute_url(),
                event_key=f"match-reminder:{favorite.user_id}:{favorite.prediction_id}:{match.id}",
                meta={"coupon_id": favorite.prediction_id, "match_id": match.id},
            )
            created += int(notification is not None)
    return created


@shared_task
def sync_achievement_notifications() -> int:
    analysts = (
        User.objects.filter(
            role=User.Role.ANALYST,
            analyst_followers__isnull=False,
        )
        .distinct()
        .select_related("analyst_profile")
    )
    created = 0

    for analyst in analysts:
        try:
            profile = analyst.analyst_profile
        except AnalystProfile.DoesNotExist:
            profile = None
        followers_count = analyst.analyst_followers.count()
        overview = build_achievement_overview(
            analyst,
            followers_count=followers_count,
            is_verified=bool(profile and profile.is_verified),
        )
        unlocked_items = [item for item in overview["items"] if item["unlocked"]]
        unlocked_keys = [item["key"] for item in unlocked_items]
        state, state_created = AchievementState.objects.get_or_create(
            user=analyst,
            defaults={"unlocked_keys": unlocked_keys},
        )
        if state_created:
            continue

        previous = set(state.unlocked_keys or [])
        new_items = [item for item in unlocked_items if item["key"] not in previous]
        if new_items:
            followers = AnalystFollow.objects.filter(analyst=analyst).select_related("follower")
            expert_name = _expert_name(analyst)
            expert_url = reverse("front:expert_profile", kwargs={"username": analyst.username})
            for item in new_items:
                for follow in followers:
                    notification = create_notification(
                        recipient=follow.follower,
                        actor=analyst,
                        kind=Notification.Kind.ACHIEVEMENT,
                        title=f"Новое достижение у {expert_name}",
                        message=f"{item['label']} — {item['description']}",
                        url=expert_url,
                        event_key=f"achievement:{follow.follower_id}:{analyst.id}:{item['key']}",
                        meta={"expert_id": analyst.id, "achievement": item["key"]},
                    )
                    created += int(notification is not None)

        if set(unlocked_keys) != previous:
            state.unlocked_keys = unlocked_keys
            state.save(update_fields=["unlocked_keys", "updated_at"])

    return created


def _absolute_url(path: str) -> str:
    if not path:
        return ""
    if path.startswith(("http://", "https://")):
        return path
    base = getattr(settings, "SITE_BASE_URL", "").rstrip("/")
    return f"{base}{path}" if base else path


def _send_telegram(chat_id: str, text: str) -> None:
    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не настроен")
    payload = json.dumps(
        {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        response.read()


@shared_task
def deliver_pending_notifications(limit: int = 300) -> dict:
    pending = (
        Notification.objects.filter(
            Q(email_processed_at__isnull=True) | Q(telegram_processed_at__isnull=True)
        )
        .select_related("recipient")
        .order_by("created_at", "id")[:limit]
    )
    now = timezone.now()
    email_sent = 0
    telegram_sent = 0

    for notification in pending:
        preferences = get_preferences(notification.recipient)
        update_fields = []
        link = _absolute_url(notification.url)
        body = notification.message
        if link:
            body = f"{body}\n\n{link}" if body else link

        if notification.email_processed_at is None:
            if not preferences.email_enabled or not notification.recipient.email:
                notification.email_processed_at = now
                update_fields.append("email_processed_at")
            else:
                try:
                    send_mail(
                        notification.title,
                        body,
                        settings.DEFAULT_FROM_EMAIL,
                        [notification.recipient.email],
                        fail_silently=False,
                    )
                except Exception:
                    pass
                else:
                    notification.email_processed_at = now
                    notification.email_sent_at = now
                    update_fields.extend(["email_processed_at", "email_sent_at"])
                    email_sent += 1

        if notification.telegram_processed_at is None:
            if not preferences.telegram_enabled or not preferences.telegram_chat_id:
                notification.telegram_processed_at = now
                update_fields.append("telegram_processed_at")
            elif getattr(settings, "TELEGRAM_BOT_TOKEN", "").strip():
                text = f"{notification.title}\n{notification.message}".strip()
                if link:
                    text = f"{text}\n\n{link}"
                try:
                    _send_telegram(preferences.telegram_chat_id, text)
                except Exception:
                    pass
                else:
                    notification.telegram_processed_at = now
                    notification.telegram_sent_at = now
                    update_fields.extend(["telegram_processed_at", "telegram_sent_at"])
                    telegram_sent += 1

        if update_fields:
            notification.save(update_fields=list(dict.fromkeys(update_fields)))

    return {"email_sent": email_sent, "telegram_sent": telegram_sent}
