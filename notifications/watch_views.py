from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_http_methods

from game.models import Match

from .models import MatchWatch, Notification
from .services import get_preferences


PAGE_SIZE = 30
ACTIVE_WATCH_SCOPES = (Match.SyncScope.PREMATCH, Match.SyncScope.LIVE)
PREDICTION_ALERT_KINDS = (
    Notification.Kind.NEW_PREDICTION,
    Notification.Kind.REQUESTED_MATCH_PREDICTION,
    Notification.Kind.PREDICTION_LIKE,
    Notification.Kind.PREDICTION_FAVORITE,
    Notification.Kind.NEW_FOLLOWER,
    Notification.Kind.COPYBETTING,
    Notification.Kind.PAID_SUBSCRIPTION,
)
MATCH_EVENT_KINDS = (
    Notification.Kind.MATCH_REMINDER,
    Notification.Kind.MATCH_PREDICTION,
)


def _selected_watch_date(request):
    raw = (request.GET.get("date") or "").strip()
    if raw:
        try:
            selected = parse_date(raw)
        except (TypeError, ValueError):
            selected = None
        if selected is not None:
            return selected
    return timezone.localdate()


def _watched_count(request) -> int:
    selected_date = _selected_watch_date(request)
    return MatchWatch.objects.filter(
        user=request.user,
        match__sync_scope__in=ACTIVE_WATCH_SCOPES,
        match__starts_at__date=selected_date,
    ).count()


def _group_notifications(page_obj):
    today = timezone.localdate()
    yesterday = today - timedelta(days=1)
    groups = {
        "today": [],
        "yesterday": [],
        "earlier": [],
    }

    for notification in page_obj.object_list:
        created_date = timezone.localtime(notification.created_at).date()
        if created_date == today:
            groups["today"].append(notification)
        elif created_date == yesterday:
            groups["yesterday"].append(notification)
        else:
            groups["earlier"].append(notification)

    return (
        {"key": "today", "title": "Сегодня", "items": groups["today"]},
        {"key": "yesterday", "title": "Вчера", "items": groups["yesterday"]},
        {"key": "earlier", "title": "Ранее", "items": groups["earlier"]},
    )


@login_required
def center(request):
    active_filter = request.GET.get("filter", "all")
    if active_filter not in {"all", "unread"}:
        active_filter = "all"

    base_queryset = Notification.objects.filter(
        recipient=request.user,
        show_in_app=True,
    )
    queryset = base_queryset.select_related("actor")
    if active_filter == "unread":
        queryset = queryset.filter(is_read=False)

    paginator = Paginator(queryset, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))
    preferences = get_preferences(request.user)
    unread_queryset = base_queryset.filter(is_read=False)
    unread_count = unread_queryset.count()

    return render(
        request,
        "notifications/center.html",
        {
            "page_obj": page_obj,
            "notification_groups": _group_notifications(page_obj),
            "preferences": preferences,
            "active_filter": active_filter,
            "unread_count": unread_count,
            "prediction_alert_count": unread_queryset.filter(kind__in=PREDICTION_ALERT_KINDS).count(),
            "match_event_count": unread_queryset.filter(kind__in=MATCH_EVENT_KINDS).count(),
        },
    )


def _watch_response(request, match: Match):
    watch = MatchWatch.objects.filter(user=request.user, match=match).first()
    is_active_match = match.sync_scope in ACTIVE_WATCH_SCOPES

    if request.method == "GET":
        return JsonResponse(
            {
                "ok": True,
                "watching": bool(watch and is_active_match),
                "scope": match.sync_scope,
                "watched_count": _watched_count(request),
            }
        )

    if not is_active_match:
        if watch:
            watch.delete()
        return JsonResponse(
            {
                "ok": False,
                "watching": False,
                "scope": match.sync_scope,
                "watched_count": _watched_count(request),
                "error": "Завершённый матч нельзя отслеживать.",
            },
            status=409,
        )

    if watch:
        watch.delete()
        watching = False
    else:
        now = timezone.now()
        MatchWatch.objects.create(
            user=request.user,
            match=match,
            last_scope=match.sync_scope,
            last_score=str(match.score or ""),
            last_time_status=str(match.time_status or ""),
            started_sent_at=now if match.sync_scope == Match.SyncScope.LIVE else None,
        )
        watching = True

    return JsonResponse(
        {
            "ok": True,
            "watching": watching,
            "scope": match.sync_scope,
            "watched_count": _watched_count(request),
        }
    )


@login_required
@require_http_methods(["GET", "POST"])
def match_watch(request, match_id: int):
    match = get_object_or_404(Match, pk=match_id)
    return _watch_response(request, match)


@login_required
@require_http_methods(["GET", "POST"])
def match_watch_by_slug(request, match_slug: str):
    match = get_object_or_404(Match, slug=match_slug)
    return _watch_response(request, match)
