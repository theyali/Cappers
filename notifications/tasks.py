import json
import re
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

from .models import AchievementState, CouponEventState, MatchWatch, Notification, TelegramAccount
from .services import create_notification, get_preferences


SETTLED_STATES = {
    PredictionCoupon.StateStatus.WIN,
    PredictionCoupon.StateStatus.LOSE,
    PredictionCoupon.StateStatus.REFUND,
}

SCORE_PATTERN = re.compile(r"(\d+)\s*[:\-]\s*(\d+)")
HALFTIME_WORDS = {"ht", "halftime", "interval", "перерыв"}


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


def _score_pair(value: str | None) -> tuple[int, int] | None:
    match = SCORE_PATTERN.search(str(value or ""))
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _canonical_score(value: str | None) -> str:
    pair = _score_pair(value)
    if pair is not None:
        return f"{pair[0]}:{pair[1]}"
    return str(value or "").strip()


def _status_fragments(match: Match) -> list[str]:
    fragments = [match.time_status or "", match.live_minute_label or ""]
    raw = match.raw_data if isinstance(match.raw_data, dict) else {}
    for key in ("status", "game_status", "time_status", "period", "phase"):
        value = raw.get(key)
        if isinstance(value, dict):
            fragments.extend(str(item or "") for item in value.values())
        elif value not in (None, ""):
            fragments.append(str(value))
    return fragments


def _is_halftime(match: Match) -> bool:
    status_text = " ".join(_status_fragments(match)).lower()
    normalized = re.sub(r"[^a-zа-я0-9]+", " ", status_text).strip()
    tokens = set(normalized.split())
    return bool(tokens & HALFTIME_WORDS) or "half time" in normalized


def _score_event_title(previous_score: str, current_score: str) -> str:
    previous_pair = _score_pair(previous_score)
    current_pair = _score_pair(current_score)
    if current_pair is not None:
        current_total = sum(current_pair)
        previous_total = sum(previous_pair) if previous_pair is not None else 0
        if current_total > previous_total:
            return f"⚽ Гол! {current_score}"
    return f"Счёт изменился: {current_score}"


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


def _watched_match_update_events() -> dict:
    watches = list(
        MatchWatch.objects.filter(
            match__sync_scope__in=(
                Match.SyncScope.PREMATCH,
                Match.SyncScope.LIVE,
                Match.SyncScope.FINISHED,
            )
        )
        .select_related(
            "user",
            "match__home_team",
            "match__away_team",
            "match__league",
        )
        .order_by("id")
    )
    now = timezone.now()
    created = 0
    removed = 0

    for watch in watches:
        match = watch.match
        score = _canonical_score(match.score)

        if match.sync_scope == Match.SyncScope.FINISHED:
            title = "Матч завершён"
            if score:
                title = f"Матч завершён · {score}"
            notification = create_notification(
                recipient=watch.user,
                kind=Notification.Kind.MATCH_REMINDER,
                title=title,
                message=_match_name(match),
                url=match.get_absolute_url(),
                event_key=f"match-final:{watch.user_id}:{match.id}",
                meta={"match_id": match.id, "event": "finished", "score": score},
            )
            created += int(notification is not None)
            watch.delete()
            removed += 1
            continue

        update_fields = []

        if match.sync_scope == Match.SyncScope.LIVE:
            if watch.started_sent_at is None:
                notification = create_notification(
                    recipient=watch.user,
                    kind=Notification.Kind.MATCH_REMINDER,
                    title="Матч начался",
                    message=_match_name(match),
                    url=match.get_absolute_url(),
                    event_key=f"match-start:{watch.user_id}:{match.id}",
                    meta={"match_id": match.id, "event": "started", "score": score},
                )
                created += int(notification is not None)
                watch.started_sent_at = now
                update_fields.append("started_sent_at")

            previous_score = _canonical_score(watch.last_score)
            if score and score != previous_score:
                pair = _score_pair(score)
                should_notify = bool(previous_score) or (pair is not None and sum(pair) > 0)
                if should_notify:
                    event_stamp = match.updated_at.strftime("%Y%m%d%H%M%S%f")
                    notification = create_notification(
                        recipient=watch.user,
                        kind=Notification.Kind.MATCH_REMINDER,
                        title=_score_event_title(previous_score, score),
                        message=_match_name(match),
                        url=match.get_absolute_url(),
                        event_key=f"match-score:{watch.user_id}:{match.id}:{event_stamp}",
                        meta={
                            "match_id": match.id,
                            "event": "score",
                            "score": score,
                            "previous_score": previous_score,
                        },
                    )
                    created += int(notification is not None)
                watch.last_score = score
                update_fields.append("last_score")

            if watch.halftime_sent_at is None and _is_halftime(match):
                title = "Перерыв"
                if score:
                    title = f"Перерыв · {score}"
                notification = create_notification(
                    recipient=watch.user,
                    kind=Notification.Kind.MATCH_REMINDER,
                    title=title,
                    message=_match_name(match),
                    url=match.get_absolute_url(),
                    event_key=f"match-halftime:{watch.user_id}:{match.id}",
                    meta={"match_id": match.id, "event": "halftime", "score": score},
                )
                created += int(notification is not None)
                watch.halftime_sent_at = now
                update_fields.append("halftime_sent_at")

        if watch.last_scope != match.sync_scope:
            watch.last_scope = match.sync_scope
            update_fields.append("last_scope")
        current_time_status = str(match.time_status or "")
        if watch.last_time_status != current_time_status:
            watch.last_time_status = current_time_status
            update_fields.append("last_time_status")

        if update_fields:
            watch.save(update_fields=list(dict.fromkeys(update_fields)))

    return {"created": created, "removed": removed}


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

    watched = _watched_match_update_events()
    return {
        "new_prediction_events": new_count,
        "settlement_events": settled_count,
        "match_update_events": watched["created"],
        "finished_watches_removed": watched["removed"],
    }


@shared_task
def notify_match_reminders() -> int:
    now = timezone.now()
    window_start = now + timedelta(minutes=55)
    window_end = now + timedelta(minutes=65)
    watches = (
        MatchWatch.objects.filter(
            match__sync_scope=Match.SyncScope.PREMATCH,
            match__starts_at__gte=window_start,
            match__starts_at__lt=window_end,
        )
        .select_related(
            "user",
            "match__home_team",
            "match__away_team",
            "match__league",
        )
        .order_by("id")
    )

    created = 0
    for watch in watches:
        match = watch.match
        notification = create_notification(
            recipient=watch.user,
            kind=Notification.Kind.MATCH_REMINDER,
            title="Матч начнётся примерно через час",
            message=_match_name(match),
            url=match.get_absolute_url(),
            event_key=f"match-reminder:{watch.user_id}:{match.id}",
            meta={"match_id": match.id, "event": "reminder"},
        )
        created += int(notification is not None)
    return created


@shared_task
def notify_watched_match_updates() -> dict:
    return _watched_match_update_events()


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
            account = (
                TelegramAccount.objects.filter(user=notification.recipient)
                .only("chat_id")
                .first()
            )
            telegram_chat_id = preferences.telegram_chat_id or (account.chat_id if account else "")
            if not preferences.telegram_enabled or not telegram_chat_id:
                notification.telegram_processed_at = now
                update_fields.append("telegram_processed_at")
            elif getattr(settings, "TELEGRAM_BOT_TOKEN", "").strip():
                text = f"{notification.title}\n{notification.message}".strip()
                if link:
                    text = f"{text}\n\n{link}"
                try:
                    _send_telegram(telegram_chat_id, text)
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
