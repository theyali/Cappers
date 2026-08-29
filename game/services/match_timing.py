from __future__ import annotations

from django.conf import settings
from django.utils import timezone

from game.models import Match


DEFAULT_SOON_WINDOW_SECONDS = 10 * 60


def soon_window_seconds() -> int:
    try:
        return max(0, int(getattr(settings, "MATCH_SOON_WINDOW_SECONDS", DEFAULT_SOON_WINDOW_SECONDS)))
    except (TypeError, ValueError):
        return DEFAULT_SOON_WINDOW_SECONDS


def prediction_window_open(match: Match, *, now=None) -> bool:
    """Return whether a new prediction can still be accepted for this match.

    Provider state is not enough here: if the scheduled start has already arrived,
    predictions are closed locally even while the provider still reports prematch.
    """
    if match.sync_scope != Match.SyncScope.PREMATCH or not match.starts_at:
        return False
    moment = now or timezone.now()
    return match.starts_at > moment


def match_timing_payload(match: Match, *, now=None) -> dict:
    moment = now or timezone.now()
    starts_at = match.starts_at
    window = soon_window_seconds()

    if match.sync_scope == Match.SyncScope.LIVE:
        state = "live"
        label = "Идет"
    elif match.sync_scope == Match.SyncScope.FINISHED:
        state = "finished"
        label = "Завершен"
    elif not starts_at:
        state = "unknown"
        label = "Время не указано"
    else:
        seconds = int((starts_at - moment).total_seconds())
        if seconds <= window:
            state = "soon"
            label = "Скоро начнется"
        else:
            state = "prematch"
            label = "До начала"

    seconds_to_start = None
    is_overdue = False
    if starts_at:
        raw_seconds = int((starts_at - moment).total_seconds())
        seconds_to_start = max(0, raw_seconds)
        is_overdue = raw_seconds <= 0

    return {
        "id": match.id,
        "scope": match.sync_scope,
        "state": state,
        "label": label,
        "starts_at": starts_at.isoformat() if starts_at else None,
        "seconds_to_start": seconds_to_start,
        "is_overdue": is_overdue,
        "prediction_open": prediction_window_open(match, now=moment),
        "soon_window_seconds": window,
    }
