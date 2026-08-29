from datetime import datetime, time, timedelta

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.db.models import BooleanField, Case, Count, Exists, IntegerField, OuterRef, Q, Value, When
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
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
SPORT_FILTERS = (
    ("all", "Все"),
    ("football", "Футбол"),
    ("hockey", "Хоккей"),
    ("basketball", "Баскетбол"),
    ("tennis", "Теннис"),
)
SPORT_SEO_LABELS = {
    "all": "по всем видам спорта",
    "football": "по футболу",
    "hockey": "по хоккею",
    "basketball": "по баскетболу",
    "tennis": "по теннису",
}
SCOPE_SEO_LABELS = {
    "all": "Матчи",
    WATCHED_SCOPE: "Отслеживаемые матчи",
    Match.SyncScope.LIVE: "Live-матчи",
    Match.SyncScope.PREMATCH: "Предстоящие матчи",
    Match.SyncScope.FINISHED: "Завершенные матчи",
}
ACTIVE_WATCH_SCOPES = (Match.SyncScope.PREMATCH, Match.SyncScope.LIVE)
MATCHES_PAGE_SIZE = 18
MAX_MATCHES_WINDOW = 180
MATCH_DATE_INDEX_WINDOW_DAYS = 30


def match_list(request, sport=None, scope=None, selected_date=None):
    """Match list filtered by scope/date with AJAX pages for infinite scroll."""
    lazy_request = _is_lazy_request(request)
    active_scope = scope or request.GET.get("scope", "all")
    valid_scopes = {scope for scope, _ in SCOPE_FILTERS}
    if active_scope not in valid_scopes:
        active_scope = "all"

    active_sport = sport or request.GET.get("sport", "all")
    valid_sports = {sport for sport, _ in SPORT_FILTERS}
    if active_sport not in valid_sports:
        active_sport = "all"

    today = timezone.localdate()
    selected_date = _selected_date(selected_date or request.GET.get("date"), today=today)
    min_match_date = today - timedelta(days=MATCH_DATE_INDEX_WINDOW_DAYS)
    max_match_date = today + timedelta(days=MATCH_DATE_INDEX_WINDOW_DAYS)

    if active_scope == Match.SyncScope.LIVE and not lazy_request:
        live_url = _match_list_url(
            request,
            scope=active_scope,
            selected_date=selected_date,
            sport=active_sport,
        )
        if request.path != live_url or any(param in request.GET for param in ("sport", "scope", "date")):
            return redirect(live_url, permanent=True)

    if active_scope != Match.SyncScope.LIVE and not _date_in_index_window(selected_date, today=today):
        raise Http404("Дата матчей вне доступного диапазона.")

    if _should_redirect_to_clean_url(request, sport=sport, scope=scope):
        return redirect(
            _match_list_url(
                request,
                scope=active_scope,
                selected_date=selected_date,
                sport=active_sport,
            ),
            permanent=False,
        )

    day_start, day_end = _local_day_bounds(selected_date)

    date_matches_all = Match.objects.filter(starts_at__gte=day_start, starts_at__lt=day_end)
    live_matches_all = Match.objects.filter(sync_scope=Match.SyncScope.LIVE)
    date_matches = _filter_by_sport(date_matches_all, active_sport)
    live_matches = _filter_by_sport(live_matches_all, active_sport)
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
                "url": _match_list_url(
                    request,
                    scope=scope,
                    selected_date=selected_date,
                    sport=active_sport,
                ),
            }
        )

    sport_count_source = _sport_count_source(
        date_matches_all,
        live_matches_all,
        active_scope,
        request.user,
    )
    sport_tabs = []
    for sport, label in SPORT_FILTERS:
        count = (
            sport_count_source.count()
            if sport == "all"
            else sport_count_source.filter(sport__code=sport).count()
        )
        sport_tabs.append(
            {
                "code": sport,
                "label": label,
                "count": count,
                "url": _match_list_url(
                    request,
                    scope=active_scope,
                    selected_date=selected_date,
                    sport=sport,
                ),
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
                    sport=active_sport,
                ),
            }
        )

    previous_date = selected_date - timedelta(days=1)
    next_date = selected_date + timedelta(days=1)
    previous_date_url = (
        _match_list_url(
            request,
            scope=active_scope,
            selected_date=previous_date,
            sport=active_sport,
        )
        if active_scope == Match.SyncScope.LIVE or previous_date >= min_match_date
        else ""
    )
    next_date_url = (
        _match_list_url(
            request,
            scope=active_scope,
            selected_date=next_date,
            sport=active_sport,
        )
        if active_scope == Match.SyncScope.LIVE or next_date <= max_match_date
        else ""
    )
    draft_coupon = _active_draft_coupon(request.user) if can_write_coupon else None
    seo = _match_list_seo(
        request,
        active_scope=active_scope,
        active_sport=active_sport,
        selected_date=selected_date,
        today=today,
    )
    context = {
        "active_scope": active_scope,
        "active_sport": active_sport,
        "scope_tabs": scope_tabs,
        "sport_tabs": sport_tabs,
        "matches": matches,
        "page_obj": page_obj,
        "total_count": total_count,
        "hero_count": _hero_count(active_scope, total_count, counts, watched_count),
        "can_write_coupon": can_write_coupon,
        "latest_predictions": _latest_predictions(),
        "draft_coupon": _serialize_draft_coupon(draft_coupon) if draft_coupon else None,
        "coupon_match_stale_seconds": settings.COUPON_MATCH_STALE_SECONDS,
        "selected_date": selected_date,
        "selected_date_iso": selected_date.isoformat(),
        "min_match_date_iso": min_match_date.isoformat(),
        "max_match_date_iso": max_match_date.isoformat(),
        "show_date_filter": active_scope != Match.SyncScope.LIVE,
        "date_picker_url_template": _match_list_url(
            request,
            scope=active_scope,
            selected_date="__DATE__",
            sport=active_sport,
        ),
        "previous_date_iso": previous_date.isoformat(),
        "previous_date_url": previous_date_url,
        "next_date_iso": next_date.isoformat(),
        "next_date_url": next_date_url,
        "date_shortcuts": date_shortcuts,
        "today_iso": today.isoformat(),
        "locked_card_odds": card_odds,
        "match_list_h1": seo["h1"],
        "match_list_hero_meta": seo["hero_meta"],
        "seo_meta": seo["meta"],
    }
    return render(request, "game/match_list.html", context)


def _filter_by_sport(queryset, sport_code: str):
    if sport_code == "all":
        return queryset
    return queryset.filter(sport__code=sport_code)


def _sport_count_source(date_matches, live_matches, active_scope: str, user):
    queryset = live_matches if active_scope == Match.SyncScope.LIVE else date_matches
    if active_scope == WATCHED_SCOPE:
        if user.is_authenticated:
            return queryset.filter(
                sync_scope__in=ACTIVE_WATCH_SCOPES,
                notification_watchers__user=user,
            ).distinct()
        return queryset.none()
    if active_scope != "all":
        return queryset.filter(sync_scope=active_scope)
    return queryset


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


def _should_redirect_to_clean_url(request, *, sport, scope) -> bool:
    if sport is not None or scope is not None or _is_lazy_request(request):
        return False
    return any(param in request.GET for param in ("sport", "scope", "date"))


def _match_list_url(request, *, scope, selected_date, sport=None):
    sport_code = sport or "all"
    if scope == Match.SyncScope.LIVE:
        return reverse("game:match_list_live", kwargs={"sport": sport_code})
    selected_date_iso = selected_date.isoformat() if hasattr(selected_date, "isoformat") else str(selected_date)
    base_url = reverse("game:match_list")
    return f"{base_url}{sport_code}/{scope}/{selected_date_iso}/"


def _date_in_index_window(selected_date, *, today) -> bool:
    min_date = today - timedelta(days=MATCH_DATE_INDEX_WINDOW_DAYS)
    max_date = today + timedelta(days=MATCH_DATE_INDEX_WINDOW_DAYS)
    return min_date <= selected_date <= max_date


def _hero_count(active_scope: str, total_count: int, counts: dict, watched_count: int) -> int:
    if active_scope == "all":
        return total_count
    if active_scope == WATCHED_SCOPE:
        return watched_count
    return counts.get(active_scope, 0)


def _match_list_seo(request, *, active_scope: str, active_sport: str, selected_date, today) -> dict:
    scope_label = SCOPE_SEO_LABELS.get(active_scope, "Матчи")
    sport_label = SPORT_SEO_LABELS.get(active_sport, "по всем видам спорта")
    date_label = selected_date.strftime("%d.%m.%Y")

    if active_scope == Match.SyncScope.LIVE:
        h1 = f"{scope_label} {sport_label}"
        title = f"{h1} — КапперХаб"
        description = f"Актуальные live-матчи {sport_label}: счет, статус игры и коэффициенты на КапперХаб."
        hero_meta = "игр сейчас"
    else:
        h1 = f"{scope_label} {sport_label} на {date_label}"
        title = f"{h1} — КапперХаб"
        description = f"{scope_label} {sport_label} на {date_label}: расписание, статусы, коэффициенты и прогнозы капперов."
        hero_meta = f"игр на {selected_date.strftime('%d.%m')}"

    robots = "index,follow"
    if active_scope == WATCHED_SCOPE or request.GET:
        robots = "noindex,follow"

    canonical_path = _match_list_url(
        request,
        scope=active_scope,
        selected_date=selected_date,
        sport=active_sport,
    )
    canonical_url = request.build_absolute_uri(canonical_path)

    return {
        "h1": h1,
        "hero_meta": hero_meta,
        "meta": {
            "page": None,
            "title": title,
            "description": description,
            "keywords": "",
            "robots": robots,
            "canonical_url": canonical_url,
            "og_title": title,
            "og_description": description,
            "og_image_url": "",
            "og_type": "website",
            "twitter_card": "summary_large_image",
            "schema_type": "",
            "schema_json_ld": "",
        },
    }


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
