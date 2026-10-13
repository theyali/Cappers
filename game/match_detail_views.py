from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.utils import timezone

from cabinet.models import MatchPredictionRequest, User
from front.metrics import increment_match_views
from game.models import Match, Prediction, PredictionCoupon
from game.services.bet_options import build_match_odds_tabs, build_match_winner_odds
from game.tasks import refresh_match_provider_predictions
from game.templatetags.match_ui import live_status_label
from notifications.models import MatchWatch

from . import views as legacy_views


PROVIDER_REFRESH_QUEUE_TTL = 300


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


def _live_progress(match: Match) -> int:
    if match.sync_scope == Match.SyncScope.FINISHED:
        return 100
    if match.sync_scope != Match.SyncScope.LIVE:
        return 0
    try:
        minute = int(match.live_minute or 0)
    except (TypeError, ValueError):
        minute = 0
    if not minute:
        return 0
    duration = 90
    if match.sport_code == "basketball":
        duration = 40
    elif match.sport_code == "hockey":
        duration = 60
    return max(0, min(100, round((minute / duration) * 100)))


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


def _h2h_matches(match: Match) -> list[dict]:
    if not match.home_team_id or not match.away_team_id:
        return []
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


def _compact_odds(odds_tabs: list[dict]) -> list[dict]:
    groups = []
    for tab in odds_tabs:
        for section in tab.get("sections", []):
            for row in section.get("rows", []):
                odds = row.get("odds", [])
                if odds:
                    groups.append(
                        {
                            "title": row.get("title") or section.get("title") or "Исход",
                            "odds": odds[:3],
                        }
                    )
                if len(groups) >= 3:
                    return groups
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
    first_half_score = str((match.raw_data or {}).get("first_time_score") or "").strip()
    h2h = _h2h_matches(match)
    return {
        "home_code": _team_code(match.home_team_name, "Х"),
        "away_code": _team_code(match.away_team_name, "Г"),
        "home_form": _team_recent_line(match, "home"),
        "away_form": _team_recent_line(match, "away"),
        "score_home": score_parts[0] if score_parts else "",
        "score_away": score_parts[1] if score_parts else "",
        "score_label": match.score if match.score else "VS",
        "first_half_score": first_half_score,
        "live_progress": _live_progress(match),
        "status_label": live_status_label(match) if match.sync_scope == Match.SyncScope.LIVE else match.get_sync_scope_display(),
        "league_badge": _team_code(match.league_name, "Л"),
        "compact_odds": _compact_odds(odds_tabs),
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

    odds_tabs = build_match_odds_tabs(match)
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
        "match_page": _match_page_context(match, odds_tabs),
        "provider_prediction_panel": legacy_views._provider_prediction_panel(match),
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

    feed_html = render_to_string(
        "game/_match_predictions_feed.html",
        context,
        request=request,
    )

    # Keep the feed shell in the first HTML response so the layout does not jump.
    # JavaScript only fills .match-predictions-list after the page is visible.
    closing_main = "</main>"
    if closing_main in page_html:
        page_html = page_html.replace(closing_main, f"{feed_html}\n{closing_main}", 1)

    return HttpResponse(page_html)
