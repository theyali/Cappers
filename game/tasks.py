from celery import shared_task
from django.conf import settings
from django.core.cache import cache

from game.models import Match, Provider
from game.services.live_settlement import settle_live_matches
from game.services.match_sync import MatchSyncService
from game.services.providers.neurokeff import NeurokeffProviderError
from game.services.settlement import settle_finished_matches


@shared_task
def fetch_upcoming_matches():
    return _fetch_upcoming_for_sport()


@shared_task
def fetch_live_matches():
    return _run_sync("live", "all", _sync_live_all)


@shared_task
def sync_stuck_live_matches():
    return _run_sync("stuck-live", "all", _sync_stuck_live)


@shared_task
def refresh_live_match_states(game_ids):
    """WS discovery/reconciliation must not touch stats, events or odds."""
    ids = sorted({value for value in game_ids if type(value) is int and value > 0})
    if not ids:
        return {"status": "skipped", "reason": "empty_ids"}
    return MatchSyncService().sync_match_states(ids)


@shared_task(bind=True, autoretry_for=(NeurokeffProviderError,), retry_backoff=5, retry_kwargs={"max_retries": 3})
def refresh_prematch_match_odds(self, game_id, sport_id, event_type="prematch.odds.available"):
    """Prematch hint -> exact REST line. Existing match state is untouched."""
    from game.services.odds_stream import ODDS_MESSAGE_TYPES, odds_sport_ids

    if (type(game_id) is not int or game_id < 1 or type(sport_id) is not int
            or sport_id not in odds_sport_ids() or event_type not in ODDS_MESSAGE_TYPES):
        return {"status": "skipped", "reason": "invalid_identity"}
    service = MatchSyncService()
    match = Match.objects.filter(provider=Provider.NEUROKEFF, external_id=game_id).select_related("sport").first()
    if match is None:
        # The notification has no league, names or kickoff: discover via REST,
        # without importing statistics/events or guessing a match's status.
        service.sync_match_states([game_id])
        match = Match.objects.filter(provider=Provider.NEUROKEFF, external_id=game_id).select_related("sport").first()
    if match is None:
        raise NeurokeffProviderError("Prematch odds game is not available in REST yet")
    if match.sport is None or match.sport.external_id != sport_id:
        return {"status": "skipped", "reason": "sport_mismatch"}
    if match.sync_scope != Match.SyncScope.PREMATCH:
        return {"status": "skipped", "reason": "not_prematch"}
    result = _run_locked(
        f"match-full-odds:{match.pk}",
        lambda: service.sync_match_bookmaker_odds(
            match, update_short=True, allow_empty_short=event_type == "prematch.odds.updated",
        ),
    )
    if result.get("reason") == "already_running":
        raise self.retry(countdown=5, max_retries=12)
    if not result.get("short_updated"):
        # The WS hint may beat the REST read replica; don't lose this one-shot hint.
        match.refresh_from_db(fields=["sync_scope"])
        if match.sync_scope == Match.SyncScope.PREMATCH:
            raise NeurokeffProviderError("Prematch short odds are not available yet")
    return result


@shared_task(bind=True, autoretry_for=(NeurokeffProviderError,), retry_backoff=5, retry_kwargs={"max_retries": 3})
def reconcile_prematch_odds(self, sport_id):
    """No WS replay: refresh the ordinary prematch list on every connection."""
    from game.services.odds_stream import odds_sport_ids

    if type(sport_id) is not int or sport_id not in odds_sport_ids():
        return {"status": "skipped", "reason": "invalid_sport"}
    sport = next(s for s in settings.NEUROKEFF_SPORTS if int(s["id"]) == sport_id)
    result = _fetch_upcoming_for_sport(sport["code"])
    if result.get("reason") in {"already_running", "provider_error"}:
        raise self.retry(countdown=30, max_retries=3)
    return result


def _sync_stuck_live():
    result = MatchSyncService().sync_stuck_live_matches()
    result["settlement"] = _settle_live()
    return result


@shared_task
def fetch_finished_matches():
    return _run_sync("finished", "all", _sync_finished_all)


def _fetch_upcoming_for_sport(sport_code: str | None = None):
    from game.services.odds_stream import queue_missing_prematch_odds

    result = _run_sync(
        "prematch",
        sport_code or "all",
        lambda: MatchSyncService().sync_upcoming(sport_code=sport_code),
    )
    if result.get("status") == "ok":
        result["full_odds_queued"] = queue_missing_prematch_odds(sport_code)
    return result


def _fetch_live_for_sport(sport_code: str):
    return _run_sync("live", sport_code, lambda: _sync_live_sport(sport_code))


def _fetch_finished_for_sport(sport_code: str):
    return _run_sync("finished", sport_code, lambda: _sync_finished_sport(sport_code))


def _sync_live_all():
    result = MatchSyncService().sync_live()
    result["settlement"] = _settle_live()
    return result


def _sync_live_sport(sport_code: str):
    result = MatchSyncService().sync_live(sport_code=sport_code)
    result["settlement"] = _settle_live()
    return result


def _sync_finished_all():
    result = MatchSyncService().sync_finished()
    settle_predictions.delay()
    result["settlement"] = "queued"
    return result


def _sync_finished_sport(sport_code: str):
    result = MatchSyncService().sync_finished(sport_code=sport_code)
    settle_predictions.delay()
    result["settlement"] = "queued"
    return result


def _lock_seconds() -> int:
    # A task killed at the time limit never reaches `finally`, so its lock must
    # expire no later than the task itself.
    lock_seconds = int(getattr(settings, "NEUROKEFF_MATCH_SYNC_LOCK_SECONDS", 600))
    return max(1, min(lock_seconds, int(settings.CELERY_TASK_TIME_LIMIT)))


def _run_locked(lock_key: str, callback):
    """Run ``callback`` unless another worker is already running it."""
    if not cache.add(lock_key, "1", timeout=_lock_seconds()):
        return {"status": "skipped", "reason": "already_running"}
    try:
        return callback()
    finally:
        cache.delete(lock_key)


def _settle_live():
    # Live settlement covers every sport: the four live sync tasks share one run.
    return _run_locked("settlement:live", settle_live_matches)


def _run_sync(scope: str, sport_code: str, callback):
    lock_key = f"match-sync:{scope}:{sport_code}"
    if not cache.add(lock_key, "1", timeout=_lock_seconds()):
        return {
            "status": "skipped",
            "reason": "already_running",
            "scope": scope,
            "sport": sport_code,
        }
    try:
        return callback()
    except NeurokeffProviderError as exc:
        return {
            "status": "error",
            "reason": "provider_error",
            "scope": scope,
            "sport": sport_code,
            "message": str(exc),
        }
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
def refresh_match_statistics(match_id: int):
    match = Match.objects.filter(pk=match_id).first()
    if match is None:
        return {
            "status": "skipped",
            "reason": "match_not_found",
            "match_id": match_id,
        }
    try:
        return MatchSyncService().sync_match_statistics(match)
    except NeurokeffProviderError as exc:
        return {
            "status": "error",
            "reason": "provider_error",
            "match_id": match_id,
            "message": str(exc),
        }


@shared_task
def refresh_match_bookmaker_odds(match_id: int):
    match = Match.objects.filter(pk=match_id).first()
    if match is None:
        return {"status": "skipped", "reason": "match_not_found", "match_id": match_id}
    try:
        return _run_locked(
            f"match-full-odds:{match_id}",
            lambda: MatchSyncService().sync_match_bookmaker_odds(match),
        )
    except NeurokeffProviderError as exc:
        return {"status": "error", "reason": "provider_error", "match_id": match_id, "message": str(exc)}


@shared_task
def refresh_match_events(match_id: int):
    match = Match.objects.filter(pk=match_id).first()
    if match is None:
        return {
            "status": "skipped",
            "reason": "match_not_found",
            "match_id": match_id,
        }
    try:
        return MatchSyncService().sync_match_events(match)
    except NeurokeffProviderError as exc:
        return {
            "status": "error",
            "reason": "provider_error",
            "match_id": match_id,
            "message": str(exc),
        }


@shared_task
def refresh_live_match_statistics():
    return _run_locked(
        "match-statistics:live",
        lambda: MatchSyncService().sync_live_statistics(),
    )


@shared_task
def refresh_live_match_events():
    return _run_locked(
        "match-events:live",
        lambda: MatchSyncService().sync_live_events(),
    )


@shared_task
def settle_predictions():
    # One settlement at a time: every finished-match sync queues this task.
    return _run_locked("settlement:finished", settle_finished_matches)
