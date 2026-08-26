from datetime import datetime, time, timedelta

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Case, Count, IntegerField, Value, When
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_date

from cabinet.models import User
from game.models import Match
from game.views import (
    SCOPE_FILTERS,
    _active_draft_coupon,
    _latest_predictions,
    _match_winner_odds,
    _serialize_draft_coupon,
)


def match_list(request):
    """Match list filtered by scope and local calendar date.

    The date defaults to today in the project timezone, so every scope tab
    (all/live/prematch/finished) starts from today's games unless the user
    explicitly selects another day.
    """
    active_scope = request.GET.get("scope", "all")
    valid_scopes = {scope for scope, _ in SCOPE_FILTERS}
    if active_scope not in valid_scopes:
        active_scope = "all"

    today = timezone.localdate()
    selected_date = _selected_date(request.GET.get("date"), today=today)
    day_start, day_end = _local_day_bounds(selected_date)

    date_matches = Match.objects.filter(
        starts_at__gte=day_start,
        starts_at__lt=day_end,
    )

    counts = {
        row["sync_scope"]: row["total"]
        for row in date_matches.values("sync_scope").annotate(total=Count("id"))
    }
    total_count = sum(counts.values())
    scope_tabs = [
        {
            "scope": scope,
            "label": label,
            "count": total_count if scope == "all" else counts.get(scope, 0),
        }
        for scope, label in SCOPE_FILTERS
    ]

    matches = date_matches.select_related(
        "sport",
        "league__country",
        "home_team",
        "away_team",
        "odds",
    )
    if active_scope != "all":
        matches = matches.filter(sync_scope=active_scope)

    matches = list(
        matches.annotate(
            scope_order=Case(
                When(sync_scope=Match.SyncScope.LIVE, then=Value(0)),
                When(sync_scope=Match.SyncScope.PREMATCH, then=Value(1)),
                When(sync_scope=Match.SyncScope.FINISHED, then=Value(2)),
                default=Value(3),
                output_field=IntegerField(),
            )
        ).order_by("scope_order", "starts_at", "id")[:60]
    )

    card_odds = {}
    for match in matches:
        match.coupon_odds = _match_winner_odds(match)
        card_odds[str(match.id)] = {
            "scope": match.sync_scope,
            "odds": _stored_card_odds(match),
        }

    can_write_coupon = (
        request.user.is_authenticated and request.user.role == User.Role.ANALYST
    )
    draft_coupon = _active_draft_coupon(request.user) if can_write_coupon else None

    context = {
        "active_scope": active_scope,
        "scope_tabs": scope_tabs,
        "matches": matches,
        "total_count": total_count,
        "can_write_coupon": can_write_coupon,
        "latest_predictions": _latest_predictions(),
        "draft_coupon": _serialize_draft_coupon(draft_coupon) if draft_coupon else None,
        "coupon_match_stale_seconds": settings.COUPON_MATCH_STALE_SECONDS,
        "selected_date": selected_date,
        "selected_date_iso": selected_date.isoformat(),
        "today_iso": today.isoformat(),
        "locked_card_odds": card_odds,
    }
    return render(request, "game/match_list.html", context)


def _stored_card_odds(match: Match) -> dict[str, str]:
    empty = {
        "home": "—",
        "draw": "—",
        "away": "—",
        "over25": "—",
        "under25": "—",
        "bttsYes": "—",
    }
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
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    if number <= 0:
        return "—"
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
    next_date = selected_date + timedelta(days=1)
    end = timezone.make_aware(datetime.combine(next_date, time.min), tz)
    return start, end
