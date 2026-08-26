from celery import shared_task

from game.services.live_settlement import settle_live_matches
from game.services.match_sync import MatchSyncService
from game.services.settlement import settle_finished_matches


@shared_task
def fetch_upcoming_matches():
    return MatchSyncService().sync_upcoming()


@shared_task
def fetch_live_matches():
    result = MatchSyncService().sync_live()
    result["settlement"] = settle_live_matches()
    return result


@shared_task
def fetch_finished_matches():
    result = MatchSyncService().sync_finished()
    result["settlement"] = settle_finished_matches()
    return result


@shared_task
def settle_predictions():
    return settle_finished_matches()
