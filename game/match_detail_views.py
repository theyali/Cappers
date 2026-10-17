import hashlib
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db.models import Count, Max, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_GET

from cabinet.models import MatchPredictionRequest, User
from front.metrics import increment_match_views
from game.models import Match, MatchEvent, MatchStatistic, Prediction, PredictionCoupon
from game.services.bet_options import build_match_odds_tabs, build_match_winner_odds
from game.services.odds_comparison import build_match_odds_comparison_ui
from game.tasks import refresh_match_events, refresh_match_provider_predictions, refresh_match_statistics, refresh_match_bookmaker_odds
from game.templatetags.match_ui import live_status_label
from notifications.models import MatchWatch

from . import views as legacy_views


PROVIDER_REFRESH_QUEUE_TTL = 300
STATISTICS_REFRESH_QUEUE_TTL = 120
EVENTS_REFRESH_QUEUE_TTL = 120


def _queue_odds_comparison_refresh(match, comparison):
    if not comparison["supported"] or match.sync_scope not in {"prematch", "live"}:
        return False
    if comparison["status"] == "match_started":
        return False
    # Even an old provider line is fetched at most once per minute per match.
    fetched = comparison["fetched_at"]
    if fetched and (timezone.now() - parse_datetime(fetched)).total_seconds() < 60:
        return False
    key = f"match-odds-comparison-queue:{match.pk}"
    try:
        if not cache.add(key, "1", timeout=60):
            return False
        refresh_match_bookmaker_odds.apply_async(args=[match.pk], retry=False)
        return True
    except Exception:
        try:
            cache.delete(key)
        except Exception:
            pass
        return False


@require_GET
def match_odds_comparison(request, slug):
    match = get_object_or_404(Match.objects.select_related("sport"), slug=slug)
    comparison = build_match_odds_comparison_ui(match)
    queued = _queue_odds_comparison_refresh(match, comparison)
    html = render_to_string("game/_match_odds_comparison_body.html", {"comparison": comparison})
    sidebar_html = render_to_string("game/_match_odds_comparison_sidebar.html", {"comparison": comparison})
    response = JsonResponse({
        "ok": True, "visible": comparison["visible"], "html": html,
        "sidebar_html": sidebar_html, "archived": comparison["archived"],
        "version": hashlib.sha256((html + sidebar_html).encode()).hexdigest(),
        "status": comparison["status"], "scope": match.sync_scope,
        "supported": comparison["supported"], "expires_at": comparison["expires_at"],
        "refresh_queued": queued,
    })
    response["Cache-Control"] = "private, no-cache"
    return response


def _provider_predictions_are_stale(match: Match) -> bool:
    if not isinstance(match.provider_predictions, dict) or not match.provider_predictions:
        return True
    if not match.provider_predictions_updated_at:
        return True
    stale_seconds = max(
        int(getattr(settings, "NEUROKEFF_GAME_PREDICTIONS_STALE_SECONDS", 3600)),
        1,
    )
    return timezone.now() - match.provider_predictions_updated_at > timedelta(
        seconds=stale_seconds
    )


def _queue_provider_predictions_refresh(match: Match) -> None:
    """Refresh provider probabilities outside the request/response path.

    Match pages must render from PostgreSQL immediately. The external provider can
    take up to NEUROKEFF_API_TIMEOUT seconds, so it must never block page opening.
    """
    if not _provider_predictions_are_stale(match):
        return

    lock_key = f"match-provider-predictions-queue:{match.pk}"
    try:
        if not cache.add(lock_key, "1", timeout=PROVIDER_REFRESH_QUEUE_TTL):
            return
        refresh_match_provider_predictions.apply_async(
            args=[match.pk],
            retry=False,
        )
    except Exception:
        # Provider enrichment is optional and must never make a match page slow
        # or unavailable when Redis/Celery is temporarily down.
        try:
            cache.delete(lock_key)
        except Exception:
            pass


def _match_statistics_are_stale(match: Match) -> bool:
    if match.sync_scope == Match.SyncScope.PREMATCH:
        return False

    aggregate = MatchStatistic.objects.filter(match=match).aggregate(
        last_fetched=Max("fetched_at"),
    )
    last_fetched = aggregate["last_fetched"]
    if last_fetched is None:
        return True
    if match.sync_scope == Match.SyncScope.FINISHED:
        return False

    stale_seconds = max(
        int(getattr(settings, "NEUROKEFF_GAME_STATISTICS_STALE_SECONDS", 60)),
        1,
    )
    return timezone.now() - last_fetched > timedelta(seconds=stale_seconds)


def _queue_match_statistics_refresh(match: Match) -> None:
    if not _match_statistics_are_stale(match):
        return

    lock_key = f"match-statistics-queue:{match.pk}"
    try:
        if not cache.add(lock_key, "1", timeout=STATISTICS_REFRESH_QUEUE_TTL):
            return
        refresh_match_statistics.apply_async(
            args=[match.pk],
            retry=False,
        )
    except Exception:
        try:
            cache.delete(lock_key)
        except Exception:
            pass


def _match_events_are_stale(match: Match) -> bool:
    if match.sync_scope == Match.SyncScope.PREMATCH:
        return False

    last_fetched = match.events_fetched_at
    if last_fetched is None:
        return True
    if match.sync_scope == Match.SyncScope.FINISHED and match.events_available is True:
        return False

    setting_name = (
        "NEUROKEFF_FINISHED_EVENTS_RETRY_SECONDS"
        if match.sync_scope == Match.SyncScope.FINISHED
        else "NEUROKEFF_GAME_EVENTS_STALE_SECONDS"
    )
    default_seconds = 3600 if match.sync_scope == Match.SyncScope.FINISHED else 60
    stale_seconds = max(int(getattr(settings, setting_name, default_seconds)), 1)
    return timezone.now() - last_fetched > timedelta(seconds=stale_seconds)


def _queue_match_events_refresh(match: Match) -> bool:
    if not _match_events_are_stale(match):
        return False

    lock_key = f"match-events-queue:{match.pk}"
    try:
        if not cache.add(lock_key, "1", timeout=EVENTS_REFRESH_QUEUE_TTL):
            return False
        refresh_match_events.apply_async(
            args=[match.pk],
            retry=False,
        )
        return True
    except Exception:
        try:
            cache.delete(lock_key)
        except Exception:
            pass
        return False


def _match_demand_context(request, match: Match) -> dict | None:
    if match.sync_scope != Match.SyncScope.PREMATCH:
        return None

    requests = MatchPredictionRequest.objects.filter(match=match)
    active = False
    if request.user.is_authenticated:
        active = requests.filter(user=request.user).exists()

    return {
        "requests_count": requests.count(),
        "active": active,
        "authenticated": request.user.is_authenticated,
    }


def _match_watch_state(request, match: Match) -> bool:
    if not request.user.is_authenticated:
        return False
    if match.sync_scope == Match.SyncScope.FINISHED:
        return False
    return MatchWatch.objects.filter(user=request.user, match=match).exists()


def _team_code(name: str, fallback: str) -> str:
    clean = str(name or "").replace("(", " ").replace(")", " ").replace("-", " ")
    parts = [part for part in clean.split() if part]
    if not parts:
        return fallback
    if len(parts) == 1:
        return parts[0][:3].upper()
    return "".join(part[0] for part in parts[:3]).upper()


def _score_parts(score: str) -> tuple[str, str] | None:
    clean = str(score or "").strip().replace(":", "-")
    if "-" not in clean:
        return None
    left, right = [part.strip() for part in clean.split("-", 1)]
    if not left or not right:
        return None
    return left, right


def _score_numbers(score: str) -> tuple[int, int] | None:
    parts = _score_parts(score)
    if not parts:
        return None
    try:
        return int(parts[0]), int(parts[1])
    except (TypeError, ValueError):
        return None


def _live_progress(match: Match, event_minutes=()) -> int:
    if match.sync_scope == Match.SyncScope.FINISHED:
        return 100
    if match.sync_scope != Match.SyncScope.LIVE:
        return 0
    try:
        minute = int(match.live_minute or 0)
    except (TypeError, ValueError):
        minute = 0
    if minute <= 0:
        # Missing provider clock is not the start of the match. Events give a
        # lower bound for progress, but never change the lifecycle or clock.
        minute = max((value for value in event_minutes if value is not None), default=0)
    duration = 90
    if match.sport_code == "basketball":
        duration = 40
    elif match.sport_code == "hockey":
        duration = 60
    return max(0, min(100, round((minute / duration) * 100)))


def _timeline_marker_label(match: Match) -> str:
    if match.sync_scope != Match.SyncScope.LIVE:
        return ""
    if match.sport_code == "tennis":
        return ""
    try:
        minute = int(match.live_minute or 0)
    except (TypeError, ValueError):
        minute = 0
    if minute > 0:
        return f"{minute}′"

    raw_label = str(match.live_minute_label or "").strip()
    if not raw_label:
        return ""
    digits = "".join(char for char in raw_label if char.isdigit() or char == "+")
    return f"{digits}′" if digits else ""


def _score_meta_label(match: Match) -> str:
    first_half_score = str((match.raw_data or {}).get("first_time_score") or "").strip()
    if first_half_score:
        return f"1-й тайм {first_half_score}"
    if match.starts_at:
        return timezone.localtime(match.starts_at).strftime("%d.%m.%Y %H:%M")
    return "Время не указано"


def _period_score_events(match: Match) -> list[dict]:
    periods = (match.raw_data or {}).get("periods") or {}
    if not isinstance(periods, dict):
        return []

    items = []
    period_items = periods.get("items")
    if isinstance(period_items, list):
        iterable = []
        for item in period_items:
            if not isinstance(item, dict):
                continue
            score = item.get("score")
            if isinstance(score, dict):
                home = score.get("home")
                away = score.get("away")
                value = f"{home}:{away}" if home not in (None, "") and away not in (None, "") else ""
            else:
                value = score
            iterable.append((item.get("code"), value, item.get("number")))
    else:
        iterable = [(key, value, None) for key, value in periods.items()]

    for key, value, number in iterable:
        period_code = str(key or "").strip().upper()
        period_score = str(value or "").strip().replace("-", ":")
        if not period_score or period_code in {"POINT", "CURRENT", "TOTAL"}:
            continue
        if period_code.startswith("S") and period_code[1:].isdigit():
            label = f"{int(number or period_code[1:])} сет {period_score}"
        elif period_code in {"1H", "H1"}:
            label = f"1-й тайм {period_score}"
        elif period_code in {"2H", "H2"}:
            label = f"2-й тайм {period_score}"
        elif period_code.startswith("P") and period_code[1:].isdigit():
            label = f"{int(number or period_code[1:])} период {period_score}"
        else:
            label = f"{period_code} {period_score}"
        items.append({"label": label, "side": ""})
    return items[:3]


def _score_events(match: Match) -> list[dict]:
    db_events = list(
        match.events_rows.filter(
            Q(event_type_code__icontains="goal")
            | Q(event_type_code__icontains="card")
            | Q(event_type_code__icontains="penalty")
            | Q(event_type_code__icontains="substitution")
            | Q(detail_code__icontains="card")
            | Q(detail_code__icontains="penalty")
        ).order_by("minute", "seq", "id")[:6]
    )
    if db_events:
        items = []
        for event in db_events:
            event_name = event.event_type_name_ru or event.event_type_name or event.event_type_code
            detail_name = event.detail_name_ru or event.detail_name or ""
            player_name = event.player_name_ru or event.player_name
            minute_label = f"{event.minute}′ " if event.minute is not None else ""
            if event.extra_minute is not None:
                minute_label = f"{event.minute}+{event.extra_minute}′ " if event.minute is not None else f"+{event.extra_minute}′ "
            label_parts = [minute_label + (player_name or event_name or "Событие")]
            if player_name and event_name:
                label_parts.append(event_name)
            if detail_name and detail_name.lower() not in {str(event_name).lower(), ""}:
                label_parts.append(detail_name)
            items.append(
                {
                    "label": " · ".join(part for part in label_parts if part).strip(),
                    "side": event.team_name_ru or event.team_name or event.team_side,
                    "type": event.event_type_code,
                }
            )
        return items

    raw = match.raw_data or {}
    raw_events = []
    for key in ("events", "incidents", "goals"):
        value = raw.get(key)
        if isinstance(value, list):
            raw_events = value
            break

    items = []
    for event in raw_events:
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("type") or event.get("event_type") or "").lower()
        if event_type and "goal" not in event_type:
            continue
        minute = event.get("minute") or event.get("time") or event.get("match_time")
        player = event.get("player_name") or event.get("player") or event.get("name")
        team = event.get("team_name") or event.get("team") or event.get("side")
        if isinstance(player, dict):
            player = player.get("ru") or player.get("name") or player.get("en")
        if isinstance(team, dict):
            team = team.get("ru") or team.get("name") or team.get("en")
        if not player and not minute:
            continue
        minute_label = f"{minute}′ " if minute not in (None, "") else ""
        items.append({"label": f"{minute_label}{player or 'Гол'}".strip(), "side": str(team or "")})
        if len(items) >= 3:
            return items

    return _period_score_events(match)


def _show_timeline(match: Match, score_events: list[dict]) -> bool:
    if match.sync_scope == Match.SyncScope.PREMATCH:
        return False
    if match.sync_scope == Match.SyncScope.LIVE:
        return True
    return bool(score_events)


def _event_time_label(event: MatchEvent) -> str:
    if event.minute is None:
        return f"+{event.extra_minute}′" if event.extra_minute is not None else ""
    if event.extra_minute is not None:
        return f"{event.minute}+{event.extra_minute}′"
    return f"{event.minute}′"


def _event_presentation(event: MatchEvent) -> dict:
    code = f"{event.event_type_code} {event.detail_code}".lower()
    raw_side = str(event.team_side or "").lower()
    if raw_side in {"home", "team1", "1"}:
        side = "home"
    elif raw_side in {"away", "team2", "2"}:
        side = "away"
    else:
        side = "neutral"
    if "yellow" in code:
        kind, icon = "yellow-card", "▮"
    elif "red" in code:
        kind, icon = "red-card", "▮"
    elif "goal" in code:
        kind, icon = "goal", "⚽"
    elif "penalty" in code:
        kind, icon = "penalty", "P"
    elif "substitut" in code or "change" in code:
        kind, icon = "substitution", "↕"
    elif "var" in code or "video" in code:
        kind, icon = "review", "VAR"
    else:
        kind, icon = "default", "•"
    return {"kind": kind, "icon": icon, "side": side}


def _serialize_match_event(event: MatchEvent) -> dict:
    linked_team = event.team
    team_name = event.team_name or (linked_team.name if linked_team else "")
    team_name_ru = event.team_name_ru or (linked_team.name_ru if linked_team else "")
    return {
        "id": event.pk,
        "key": event.event_key,
        "external_id": event.external_id,
        "uid": event.uid,
        "seq": event.seq,
        "presentation": _event_presentation(event),
        "type": {
            "code": event.event_type_code,
            "name": event.event_type_name,
            "name_ru": event.event_type_name_ru,
        },
        "detail": {
            "code": event.detail_code,
            "name": event.detail_name,
            "name_ru": event.detail_name_ru,
        },
        "time": {
            "minute": event.minute,
            "extra": event.extra_minute,
            "label": _event_time_label(event),
        },
        "team": {
            "id": event.team_id,
            "external_id": event.team_external_id,
            "name": team_name,
            "name_ru": team_name_ru,
            "side": event.team_side,
        },
        "player": {
            "external_id": event.player_external_id,
            "name": event.player_name,
            "name_ru": event.player_name_ru,
        },
        "assist": {
            "external_id": event.assist_external_id,
            "name": event.assist_name,
            "name_ru": event.assist_name_ru,
        },
        "participants": [
            {
                "role": participant.role,
                "player": {
                    "external_id": participant.player_external_id,
                    "name": participant.player_name,
                    "name_ru": participant.player_name_ru,
                },
            }
            for participant in event.participants_rows.all()
        ],
        "fetched_at": event.fetched_at.isoformat() if event.fetched_at else None,
        "updated_at": event.updated_at.isoformat(),
    }


def _match_events_state(match: Match, event_count: int) -> str:
    if match.events_fetched_at is None:
        return "pending"
    if match.events_available is False:
        return "unavailable"
    if match.events_available is None:
        return "invalid"
    return "ready" if event_count else "empty"


def _match_events_ui(match: Match) -> dict:
    events = list(
        match.events_rows.select_related("team")
        .prefetch_related("participants_rows")
        .all()
    )
    state = _match_events_state(match, len(events))
    copy = {
        "pending": (
            "Ожидаем начало матча",
            "События появятся здесь после стартового свистка.",
            "Ожидаем данные",
        ),
        "unavailable": (
            "Хронология недоступна",
            "Поставщик не передаёт события для этого матча.",
            "Нет данных",
        ),
        "invalid": (
            "Ожидаем данные",
            "Источник ещё не подтвердил доступность хронологии.",
            "Ожидаем данные",
        ),
        "empty": (
            "Событий пока нет",
            "Как только что-то произойдёт, хронология обновится автоматически.",
            "Событий пока нет",
        ),
        "ready": (
            "Событий пока нет",
            "Хронология матча обновляется автоматически.",
            "Обновляется автоматически"
            if match.sync_scope == Match.SyncScope.LIVE
            else "Хронология матча",
        ),
    }
    empty_title, empty_text, status_label = copy[state]
    return {
        "items": [_serialize_match_event(event) for event in events],
        "count": len(events),
        "state": state,
        "empty_title": empty_title,
        "empty_text": empty_text,
        "status_label": status_label,
    }


@require_GET
def match_events(request, slug: str):
    match = get_object_or_404(
        Match.objects.select_related("sport"),
        slug=slug,
    )
    events = list(
        match.events_rows.select_related("team")
        .prefetch_related("participants_rows")
        .all()
    )
    stale = _match_events_are_stale(match)
    refresh_queued = _queue_match_events_refresh(match) if stale else False
    latest_updated_at = max(
        [match.updated_at, *(event.updated_at for event in events)],
    )
    score_parts = _score_parts(match.score)
    version = ":".join(
        (
            str(match.pk),
            str(int(latest_updated_at.timestamp() * 1_000_000)),
            str(len(events)),
            str(match.events_available),
        )
    )
    response = JsonResponse(
        {
            "ok": True,
            "version": version,
            "updated_at": latest_updated_at.isoformat(),
            "match": {
                "id": match.pk,
                "external_id": match.external_id,
                "slug": match.slug,
                "scope": match.sync_scope,
                "status": (
                    live_status_label(match)
                    if match.sync_scope == Match.SyncScope.LIVE
                    else match.get_sync_scope_display()
                ),
                "score": {
                    "display": match.score,
                    "home": score_parts[0] if score_parts else None,
                    "away": score_parts[1] if score_parts else None,
                },
                "minute": match.live_minute,
                "minute_label": match.live_minute_label,
                "timeline_label": _timeline_marker_label(match),
                "progress": _live_progress(match, (event.minute for event in events)),
            },
            "events_state": {
                "status": _match_events_state(match, len(events)),
                "available": match.events_available,
                "empty": match.events_available is True and not events,
                "stale": stale,
                "fetched_at": (
                    match.events_fetched_at.isoformat()
                    if match.events_fetched_at
                    else None
                ),
                "refresh_queued": refresh_queued,
            },
            "events": [_serialize_match_event(event) for event in events],
        }
    )
    response["Cache-Control"] = "private, no-cache"
    return response


def _team_recent_line(match: Match, side: str) -> str:
    team = match.home_team if side == "home" else match.away_team
    if not team:
        return "форма команды пока недоступна"
    queryset = (
        Match.objects.filter(Q(home_team=team) | Q(away_team=team))
        .exclude(pk=match.pk)
        .filter(score__gt="")
        .order_by("-starts_at", "-id")[:6]
    )
    wins = draws = losses = 0
    for item in queryset:
        parts = _score_numbers(item.score)
        if not parts:
            continue
        home_score, away_score = parts
        team_is_home = item.home_team_id == team.pk
        team_score = home_score if team_is_home else away_score
        rival_score = away_score if team_is_home else home_score
        if team_score > rival_score:
            wins += 1
        elif team_score == rival_score:
            draws += 1
        else:
            losses += 1
    total = wins + draws + losses
    if not total:
        return "последние игры не найдены"
    return f"{wins} побед · {draws} ничьих · {losses} поражений"


def _h2h_matches(match: Match) -> dict:
    if not match.home_team_id or not match.away_team_id:
        return {"items": [], "summary": ""}
    rows = (
        Match.objects.select_related("league")
        .filter(
            Q(home_team_id=match.home_team_id, away_team_id=match.away_team_id)
            | Q(home_team_id=match.away_team_id, away_team_id=match.home_team_id)
        )
        .exclude(pk=match.pk)
        .filter(score__gt="")
        .order_by("-starts_at", "-id")[:5]
    )
    items = []
    home_wins = away_wins = draws = 0
    for item in rows:
        parts = _score_numbers(item.score)
        result = "X"
        if parts:
            home_score, away_score = parts
            if home_score == away_score:
                draws += 1
            else:
                current_home_won = (
                    item.home_team_id == match.home_team_id and home_score > away_score
                ) or (
                    item.away_team_id == match.home_team_id and away_score > home_score
                )
                if current_home_won:
                    home_wins += 1
                    result = "П1"
                else:
                    away_wins += 1
                    result = "П2"
        items.append(
            {
                "date": item.starts_at,
                "league": item.league_name or "Лига",
                "title": f"{item.home_team_name or 'Хозяева'} {item.score} {item.away_team_name or 'Гости'}",
                "result": result,
            }
        )
    return {
        "items": items,
        "summary": f"{match.home_team_name or 'Хозяева'} {home_wins} · ничьи {draws} · {match.away_team_name or 'Гости'} {away_wins}",
    }


def _odds_groups(odds_tabs: list[dict]) -> list[dict]:
    groups = []
    seen = set()
    for tab in odds_tabs:
        for section in tab.get("sections", []):
            for row in section.get("rows", []):
                odds = []
                for odd in row.get("odds", []):
                    key = (odd["market"], odd.get("outcome_code") or odd["selection"].casefold())
                    if key not in seen:
                        seen.add(key)
                        odds.append(odd)
                if odds:
                    groups.append(
                        {
                            "title": row.get("title") or section.get("title") or "Исход",
                            "odds": odds,
                        }
                    )
    return groups


def _prediction_votes(match: Match) -> dict:
    queryset = Prediction.objects.filter(
        match=match,
        coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        coupon__audience=PredictionCoupon.Audience.FREE,
    )
    total = queryset.values("coupon_id").distinct().count()
    if not total:
        return {"total": 0, "items": []}
    rows = (
        queryset.values("selection")
        .annotate(count=Count("coupon_id", distinct=True))
        .order_by("-count", "selection")[:3]
    )
    palette = ("home", "draw", "away")
    return {
        "total": total,
        "items": [
            {
                "label": row["selection"],
                "count": row["count"],
                "percent": round((row["count"] / total) * 100),
                "tone": palette[index] if index < len(palette) else "draw",
            }
            for index, row in enumerate(rows)
        ],
    }


def _match_stats_rows(match: Match) -> list[dict]:
    queryset = MatchStatistic.objects.filter(match=match).order_by(
        "period_code",
        "sort_order",
        "stat_name_ru",
        "stat_name",
        "id",
    )
    db_rows = list(queryset.filter(period_code=""))
    if not db_rows:
        db_rows = list(queryset)
    if db_rows:
        normalized = []
        for row in db_rows:
            home_number = float(row.home_value or 0)
            away_number = float(row.away_value or 0)
            max_value = max(home_number + away_number, 1)
            home_percent = round((home_number / max_value) * 100)
            away_percent = max(0, 100 - home_percent)
            normalized.append(
                {
                    "label": row.stat_name_ru or row.stat_name or row.stat_code,
                    "home": row.home_display,
                    "away": row.away_display,
                    "home_percent": home_percent,
                    "away_percent": away_percent,
                    "home_is_better": home_number >= away_number,
                    "away_is_better": away_number >= home_number,
                }
            )
        return normalized

    statistics = (match.raw_data or {}).get("statistics") or {}
    rows = statistics.get("items") if isinstance(statistics, dict) else []
    if not isinstance(rows, list):
        return []
    normalized = []
    for item in rows[:6]:
        if not isinstance(item, dict):
            continue
        label = item.get("name") or item.get("label") or item.get("type")
        home = item.get("home") or item.get("home_value") or item.get("team1")
        away = item.get("away") or item.get("away_value") or item.get("team2")
        if label and home not in (None, "") and away not in (None, ""):
            try:
                home_number = float(str(home).replace("%", "").replace(",", "."))
                away_number = float(str(away).replace("%", "").replace(",", "."))
            except (TypeError, ValueError):
                home_number = away_number = 0
            max_value = max(home_number + away_number, 1)
            normalized.append(
                {
                    "label": label,
                    "home": home,
                    "away": away,
                    "home_percent": round((home_number / max_value) * 100),
                }
            )
    return normalized


def _match_page_context(match: Match, odds_tabs: list[dict]) -> dict:
    score_parts = _score_parts(match.score)
    h2h = _h2h_matches(match)
    score_events = _score_events(match)
    events = _match_events_ui(match)
    odds_groups = _odds_groups(odds_tabs)
    return {
        "home_code": _team_code(match.home_team_name, "Х"),
        "away_code": _team_code(match.away_team_name, "Г"),
        "home_form": _team_recent_line(match, "home"),
        "away_form": _team_recent_line(match, "away"),
        "score_home": score_parts[0] if score_parts else "",
        "score_away": score_parts[1] if score_parts else "",
        "score_label": match.score if match.score else "VS",
        "score_meta": _score_meta_label(match),
        "score_events": score_events,
        "events": events,
        "event_duration": {"basketball": 40, "hockey": 60}.get(match.sport_code, 90),
        "live_progress": _live_progress(match, (item["time"]["minute"] for item in events["items"])),
        "timeline_marker_label": _timeline_marker_label(match),
        "show_timeline": _show_timeline(match, score_events),
        "status_label": live_status_label(match) if match.sync_scope == Match.SyncScope.LIVE else match.get_sync_scope_display(),
        "league_badge": _team_code(match.league_name, "Л"),
        "compact_odds": odds_groups[:3],
        "additional_odds": odds_groups[3:],
        "votes": _prediction_votes(match),
        "stats_rows": _match_stats_rows(match),
        "h2h": h2h,
    }


def match_detail(request, slug: str):
    match = get_object_or_404(
        Match.objects.select_related(
            "sport",
            "league__country",
            "home_team__country",
            "away_team__country",
            "odds",
        ),
        slug=slug,
    )
    match_metrics = increment_match_views(match.pk)

    can_write_coupon = (
        request.user.is_authenticated and request.user.role == User.Role.ANALYST
    )
    draft_coupon = (
        legacy_views._active_draft_coupon(request.user) if can_write_coupon else None
    )

    match.coupon_odds = build_match_winner_odds(match)
    # Resolve the watch state before rendering HTML, so the first response
    # already contains the correct bookmark icon state.
    match.is_watched = _match_watch_state(request, match)
    match._watched_for_request = match.is_watched

    # Render only DB-backed data. A slow HTTP call to Neurokeff used to happen
    # here synchronously and was the reason every uncached match page could wait
    # for the provider timeout. Refresh it in Celery instead.
    _queue_provider_predictions_refresh(match)
    _queue_match_statistics_refresh(match)
    _queue_match_events_refresh(match)

    odds_tabs = build_match_odds_tabs(match)
    match_page = _match_page_context(match, odds_tabs)
    match_page["comparison"] = build_match_odds_comparison_ui(match)
    _queue_odds_comparison_refresh(match, match_page["comparison"])
    match_page["has_predictions"] = True
    match_page["has_tabs"] = any(
        (
            match_page["compact_odds"],
            match_page["has_predictions"],
            match_page["stats_rows"],
            match_page["h2h"]["items"],
        )
    )
    context = {
        "match": match,
        "match_metrics": match_metrics,
        "can_write_coupon": can_write_coupon,
        "latest_predictions": legacy_views._latest_predictions(),
        "draft_coupon": (
            legacy_views._serialize_draft_coupon(draft_coupon)
            if draft_coupon
            else None
        ),
        "coupon_match_stale_seconds": settings.COUPON_MATCH_STALE_SECONDS,
        "odds_tabs": odds_tabs,
        "match_page": match_page,
        "match_predictions_total": match_metrics.predictions_count,
        "match_demand": _match_demand_context(request, match),
        "is_watched": match.is_watched,
    }

    page_html = render_to_string("game/match_detail.html", context, request=request)

    if context["match_demand"]:
        demand_html = render_to_string(
            "game/_match_demand_card.html",
            context,
            request=request,
        )
        # The demand shell is part of the first response. JavaScript only toggles
        # the already-rendered state, so opening the match no longer shifts layout.
        closing_card = "</article>"
        if closing_card in page_html:
            page_html = page_html.replace(
                closing_card,
                f"{closing_card}\n{demand_html}",
                1,
            )

        demand_js = static("front/js/match-demand.js")
        if demand_js not in page_html:
            page_html = page_html.replace(
                "</body>",
                f'    <script src="{demand_js}" defer></script>\n</body>',
                1,
            )

    if "data-match-predictions-feed" not in page_html:
        feed_html = render_to_string(
            "game/_match_predictions_feed.html",
            context,
            request=request,
        )

        # Keep the feed shell in the first HTML response so the layout does not jump.
        # JavaScript only fills .match-predictions-list after the page is visible.
        closing_main = "</main>"
        if closing_main in page_html:
            page_html = page_html.replace(
                closing_main,
                f"{feed_html}\n{closing_main}",
                1,
            )

    return HttpResponse(page_html)
