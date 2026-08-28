from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Case, IntegerField, Value, When
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_http_methods

from game.models import Match

from .models import MatchWatch, Notification, TelegramAccount
from .services import get_preferences
from .telegram_bot import get_bot_token


PAGE_SIZE = 30
ACTIVE_WATCH_SCOPES = (Match.SyncScope.PREMATCH, Match.SyncScope.LIVE)


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


@login_required
def center(request):
    active_filter = request.GET.get("filter", "all")
    if active_filter not in {"all", "unread"}:
        active_filter = "all"

    queryset = Notification.objects.filter(recipient=request.user, show_in_app=True).select_related("actor")
    if active_filter == "unread":
        queryset = queryset.filter(is_read=False)

    paginator = Paginator(queryset, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))
    preferences = get_preferences(request.user)
    telegram_account = TelegramAccount.objects.filter(user=request.user).first()
    unread_count = Notification.objects.filter(recipient=request.user, show_in_app=True, is_read=False).count()
    watched_matches = (
        MatchWatch.objects.filter(user=request.user, match__sync_scope__in=ACTIVE_WATCH_SCOPES)
        .select_related("match__home_team", "match__away_team", "match__league")
        .annotate(
            watch_scope_order=Case(
                When(match__sync_scope=Match.SyncScope.LIVE, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .order_by("watch_scope_order", "match__starts_at", "id")[:8]
    )

    return render(
        request,
        "notifications/center.html",
        {
            "page_obj": page_obj,
            "preferences": preferences,
            "telegram_account": telegram_account,
            "active_filter": active_filter,
            "unread_count": unread_count,
            "watched_matches": watched_matches,
            "telegram_bot_configured": bool(get_bot_token()),
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
