from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.utils import timezone

from cabinet.models import User
from game.models import Match, Prediction, PredictionCoupon
from game.tasks import refresh_match_provider_predictions

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


def _published_match_predictions_count(match: Match) -> int:
    return (
        Prediction.objects.filter(
            match=match,
            coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        )
        .values("coupon_id")
        .distinct()
        .count()
    )


def match_detail(request, slug: str):
    match = get_object_or_404(
        Match.objects.select_related(
            "sport",
            "league__country",
            "home_team",
            "away_team",
            "odds",
        ),
        slug=slug,
    )

    can_write_coupon = (
        request.user.is_authenticated and request.user.role == User.Role.ANALYST
    )
    draft_coupon = (
        legacy_views._active_draft_coupon(request.user) if can_write_coupon else None
    )

    match.coupon_odds = legacy_views._match_winner_odds(match)

    # Render only DB-backed data. A slow HTTP call to Neurokeff used to happen
    # here synchronously and was the reason every uncached match page could wait
    # for the provider timeout. Refresh it in Celery instead.
    _queue_provider_predictions_refresh(match)

    context = {
        "match": match,
        "can_write_coupon": can_write_coupon,
        "latest_predictions": legacy_views._latest_predictions(),
        "draft_coupon": (
            legacy_views._serialize_draft_coupon(draft_coupon)
            if draft_coupon
            else None
        ),
        "coupon_match_stale_seconds": settings.COUPON_MATCH_STALE_SECONDS,
        "odds_tabs": legacy_views._match_odds_tabs(match),
        "provider_prediction_panel": legacy_views._provider_prediction_panel(match),
        "match_predictions_total": _published_match_predictions_count(match),
    }

    page_html = render_to_string("game/match_detail.html", context, request=request)
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
