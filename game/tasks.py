from celery import shared_task
from django.conf import settings
from django.core.cache import cache

from game.models import Match
from game.services.live_settlement import settle_live_matches
from game.services.match_sync import MatchSyncService
from game.services.settlement import settle_finished_matches


@shared_task
def fetch_upcoming_matches():
    return _run_sync("prematch", "all", lambda: MatchSyncService().sync_upcoming())


@shared_task
def fetch_live_matches():
    return _run_sync("live", "all", _sync_live_all)


@shared_task
def sync_stuck_live_matches():
    return _run_sync("stuck-live", "all", _sync_stuck_live)


def _sync_stuck_live():
    result = MatchSyncService().sync_stuck_live_matches()
    result["settlement"] = settle_live_matches()
    return result


@shared_task
def fetch_finished_matches():
    return _run_sync("finished", "all", _sync_finished_all)


def _fetch_upcoming_for_sport(sport_code: str):
    return _run_sync(
        "prematch",
        sport_code,
        lambda: MatchSyncService().sync_upcoming(sport_code=sport_code),
    )


def _fetch_live_for_sport(sport_code: str):
    return _run_sync("live", sport_code, lambda: _sync_live_sport(sport_code))


def _fetch_finished_for_sport(sport_code: str):
    return _run_sync("finished", sport_code, lambda: _sync_finished_sport(sport_code))


def _sync_live_all():
    result = MatchSyncService().sync_live()
    result["settlement"] = settle_live_matches()
    return result


def _sync_live_sport(sport_code: str):
    result = MatchSyncService().sync_live(sport_code=sport_code)
    result["settlement"] = settle_live_matches()
    return result


def _sync_finished_all():
    result = MatchSyncService().sync_finished()
    result["settlement"] = settle_finished_matches()
    return result


def _sync_finished_sport(sport_code: str):
    result = MatchSyncService().sync_finished(sport_code=sport_code)
    result["settlement"] = settle_finished_matches()
    return result


def _run_sync(scope: str, sport_code: str, callback):
    lock_key = f"match-sync:{scope}:{sport_code}"
    lock_seconds = max(int(getattr(settings, "NEUROKEFF_MATCH_SYNC_LOCK_SECONDS", 600)), 1)
    if not cache.add(lock_key, "1", timeout=lock_seconds):
        return {
            "status": "skipped",
            "reason": "already_running",
            "scope": scope,
            "sport": sport_code,
        }
    try:
        return callback()
    finally:
        cache.delete(lock_key)


@shared_task
def fetch_upcoming_tennis_matches():
    return _fetch_upcoming_for_sport("tennis")


@shared_task
def fetch_upcoming_football_matches():
    return _fetch_upcoming_for_sport("football")


@shared_task
def fetch_upcoming_hockey_matches():
    return _fetch_upcoming_for_sport("hockey")


@shared_task
def fetch_upcoming_basketball_matches():
    return _fetch_upcoming_for_sport("basketball")


@shared_task
def fetch_live_tennis_matches():
    return _fetch_live_for_sport("tennis")


@shared_task
def fetch_live_football_matches():
    return _fetch_live_for_sport("football")


@shared_task
def fetch_live_hockey_matches():
    return _fetch_live_for_sport("hockey")


@shared_task
def fetch_live_basketball_matches():
    return _fetch_live_for_sport("basketball")


@shared_task
def fetch_finished_tennis_matches():
    return _fetch_finished_for_sport("tennis")


@shared_task
def fetch_finished_football_matches():
    return _fetch_finished_for_sport("football")


@shared_task
def fetch_finished_hockey_matches():
    return _fetch_finished_for_sport("hockey")


@shared_task
def fetch_finished_basketball_matches():
    return _fetch_finished_for_sport("basketball")


@shared_task
def refresh_match_provider_predictions(match_id: int):
    match = Match.objects.filter(pk=match_id).first()
    if match is None:
        return {
            "status": "skipped",
            "reason": "match_not_found",
            "match_id": match_id,
        }
    return MatchSyncService().sync_match_predictions(match)


@shared_task
def settle_predictions():
    return settle_finished_matches()
