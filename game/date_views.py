from datetime import datetime, time, timedelta

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.models import BooleanField, Case, Count, Exists, IntegerField, OuterRef, Q, Value, When
from django.http import JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.dateparse import parse_date

from cabinet.models import User
from game.models import Match, PredictionCoupon
from game.views import (
    _active_draft_coupon,
    _latest_predictions,
    _match_winner_odds,
    _serialize_draft_coupon,
)
from notifications.models import MatchWatch


WATCHED_SCOPE = "watched"
SCOPE_FILTERS = (
    ("all", "Все"),
    (WATCHED_SCOPE, "Отслеживаемые"),
    (Match.SyncScope.LIVE, "Идут сейчас"),
    (Match.SyncScope.PREMATCH, "Предстоящие"),
    (Match.SyncScope.FINISHED, "Завершенные"),
)
ACTIVE_WATCH_SCOPES = (Match.SyncScope.PREMATCH, Match.SyncScope.LIVE)
MATCHES_PAGE_SIZE = 18
MAX_MATCHES_WINDOW = 180


def match_list(request):
    """Match list filtered by scope/date with AJAX pages for infinite scroll."""
    active_scope = request.GET.get("scope", "all")
    valid_scopes = {scope for scope, _ in SCOPE_FILTERS}
    if active_scope not in valid_scopes:
        active_scope = "all"

    today = timezone.localdate()
    selected_date = _selected_date(request.GET.get("date"), today=today)
    day_start, day_end = _local_day_bounds(selected_date)

    date_matches = Match.objects.filter(starts_at__gte=day_start, starts_at__lt=day_end)
    live_matches = Match.objects.filter(sync_scope=Match.SyncScope.LIVE)
    base_matches = live_matches if active_scope == Match.SyncScope.LIVE else date_matches

    matches_queryset = base_matches.select_related(
        "sport", "league__country", "home_team", "away_team", "odds"
    )

    if active_scope == WATCHED_SCOPE:
        if request.user.is_authenticated:
            matches_queryset = matches_queryset.filter(
                sync_scope__in=ACTIVE_WATCH_SCOPES,
                notification_watchers__user=request.user,
            ).distinct()
        else:
            matches_queryset = matches_queryset.none()
    elif active_scope != "all":
        matches_queryset = matches_queryset.filter(sync_scope=active_scope)

    if request.user.is_authenticated:
        watch_exists = MatchWatch.objects.filter(
            user=request.user,
            match_id=OuterRef("pk"),
            match__sync_scope__in=ACTIVE_WATCH_SCOPES,
        )
        watched_annotation = Exists(watch_exists)
    else:
        watched_annotation = Value(False, output_field=BooleanField())

    matches_queryset = matches_queryset.annotate(
        is_watched=watched_annotation,
        scope_order=Case(
            When(sync_scope=Match.SyncScope.LIVE, then=Value(0)),
            When(sync_scope=Match.SyncScope.PREMATCH, then=Value(1)),
            When(sync_scope=Match.SyncScope.FINISHED, then=Value(2)),
            default=Value(3),
            output_field=IntegerField(),
        ),
        predictions_count=Count(
            "predictions__coupon",
            filter=Q(predictions__coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED),
            distinct=True,
        ),
    ).order_by("-is_watched", "scope_order", "starts_at", "id")

    lazy_request = _is_lazy_request(request)
    can_write_coupon = request.user.is_authenticated and request.user.role == User.Role.ANALYST
    window_size = _window_size(request.GET.get("window")) if lazy_request else None

    if window_size is not None:
        total = matches_queryset.count()
        matches = list(matches_queryset[:window_size])
        _decorate_matches(matches)
        html = render_to_string(
            "game/includes/_match_grid_items.html",
            {"matches": matches, "can_write_coupon": can_write_coupon},
            request=request,
        )
        loaded_pages = (len(matches) + MATCHES_PAGE_SIZE - 1) // MATCHES_PAGE_SIZE
        has_next = total > len(matches)
        return JsonResponse(
            {
                "ok": True,
                "html": html,
                "page": loaded_pages,
                "has_next": has_next,
                "next_page": loaded_pages + 1 if has_next else None,
                "window": len(matches),
            }
        )

    paginator = Paginator(matches_queryset, MATCHES_PAGE_SIZE)
    raw_page = request.GET.get("page", "1")
    try:
        page_obj = paginator.page(raw_page)
    except PageNotAnInteger:
        page_obj = paginator.page(1)
    except EmptyPage:
        if lazy_request:
            return JsonResponse({"ok": True, "html": "", "page": None, "has_next": False, "next_page": None})
        page_obj = paginator.page(paginator.num_pages)

    matches = list(page_obj.object_list)
    card_odds = _decorate_matches(matches)

    if lazy_request:
        html = render_to_string(
            "game/includes/_match_grid_items.html",
            {"matches": matches, "can_write_coupon": can_write_coupon},
            request=request,
        )
        return JsonResponse(
            {
                "ok": True,
                "html": html,
                "page": page_obj.number,
                "has_next": page_obj.has_next(),
                "next_page": page_obj.next_page_number() if page_obj.has_next() else None,
            }
        )

    counts = {row["sync_scope"]: row["total"] for row in date_matches.values("sync_scope").annotate(total=Count("id"))}
    total_count = sum(counts.values())
    counts[Match.SyncScope.LIVE] = live_matches.count()
    watched_count = 0
    if request.user.is_authenticated:
        watched_count = date_matches.filter(
            sync_scope__in=ACTIVE_WATCH_SCOPES,
            notification_watchers__user=request.user,
        ).distinct().count()

    scope_tabs = []
    for scope, label in SCOPE_FILTERS:
        if scope == "all":
            count = total_count
        elif scope == WATCHED_SCOPE:
            count = watched_count
        else:
            count = counts.get(scope, 0)
        scope_tabs.append(
            {
                "scope": scope,
                "label": label,
                "count": count,
                "url": _match_list_url(request, scope=scope, selected_date=selected_date),
            }
        )

    date_shortcuts = []
    for label, shortcut_date in (
        ("Вчера", today - timedelta(days=1)),
        ("Сегодня", today),
        ("Завтра", today + timedelta(days=1)),
    ):
        date_shortcuts.append(
            {
                "label": label,
                "date": shortcut_date,
                "iso": shortcut_date.isoformat(),
                "is_active": shortcut_date == selected_date,
                "url": _match_list_url(
                    request,
                    scope=active_scope,
                    selected_date=shortcut_date,
                ),
            }
        )

    previous_date = selected_date - timedelta(days=1)
    next_date = selected_date + timedelta(days=1)
    draft_coupon = _active_draft_coupon(request.user) if can_write_coupon else None
    context = {
        "active_scope": active_scope,
        "scope_tabs": scope_tabs,
        "matches": matches,
        "page_obj": page_obj,
        "total_count": total_count,
        "can_write_coupon": can_write_coupon,
        "latest_predictions": _latest_predictions(),
        "draft_coupon": _serialize_draft_coupon(draft_coupon) if draft_coupon else None,
        "coupon_match_stale_seconds": settings.COUPON_MATCH_STALE_SECONDS,
        "selected_date": selected_date,
        "selected_date_iso": selected_date.isoformat(),
        "previous_date_iso": previous_date.isoformat(),
        "previous_date_url": _match_list_url(
            request,
            scope=active_scope,
            selected_date=previous_date,
        ),
        "next_date_iso": next_date.isoformat(),
        "next_date_url": _match_list_url(
            request,
            scope=active_scope,
            selected_date=next_date,
        ),
        "date_shortcuts": date_shortcuts,
        "today_iso": today.isoformat(),
        "locked_card_odds": card_odds,
    }
    return render(request, "game/match_list.html", context)


def _decorate_matches(matches):
    card_odds = {}
    for match in matches:
        match.coupon_odds = _match_winner_odds(match)
        card_odds[str(match.id)] = {"scope": match.sync_scope, "odds": _stored_card_odds(match)}
    return card_odds


def _window_size(raw_value):
    if raw_value in (None, ""):
        return None
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return None
    return max(MATCHES_PAGE_SIZE, min(MAX_MATCHES_WINDOW, value))


def _is_lazy_request(request) -> bool:
    return request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.GET.get("lazy") == "1"


def _match_list_url(request, *, scope, selected_date):
    query = request.GET.copy()
    query["scope"] = scope
    query["date"] = selected_date.isoformat()
    query.pop("page", None)
    query.pop("lazy", None)
    encoded_query = query.urlencode()
    return f"{request.path}?{encoded_query}" if encoded_query else request.path


def _stored_card_odds(match: Match) -> dict[str, str]:
    empty = {"home": "", "draw": "", "away": "", "over25": "", "under25": "", "bttsYes": ""}
    try:
        odds = match.odds
    except ObjectDoesNotExist:
        return empty

    totals = odds.totals_all if isinstance(odds.totals_all, dict) else {}
    return {
        "home": _display_odd(odds.home_win_bet),
        "draw": _display_odd(odds.x_bet),
        "away": _display_odd(odds.away_win_bet),
        "over25": _display_odd(odds.goals_over_2_5 or totals.get("Over 2.5")),
        "under25": _display_odd(odds.goals_under_2_5 or totals.get("Under 2.5")),
        "bttsYes": _display_odd(odds.btts_yes),
    }


def _display_odd(value) -> str:
    if value in (None, ""):
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if number <= 0:
        return ""
    return f"{number:.2f}"


def _selected_date(raw_value: str | None, *, today=None):
    if raw_value:
        try:
            parsed = parse_date(raw_value)
        except (TypeError, ValueError):
            parsed = None
        if parsed is not None:
            return parsed
    return today or timezone.localdate()


def _local_day_bounds(selected_date):
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(selected_date, time.min), tz)
    end = timezone.make_aware(datetime.combine(selected_date + timedelta(days=1), time.min), tz)
    return start, end
