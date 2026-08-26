from celery import shared_task

from game.services.settlement import settle_finished_matches
from game.services.match_sync import MatchSyncService


@shared_task
def fetch_upcoming_matches():
    return MatchSyncService().sync_upcoming()


@shared_task
def fetch_live_matches():
    return MatchSyncService().sync_live()


@shared_task
def fetch_finished_matches():
    result = MatchSyncService().sync_finished()
    result["settlement"] = settle_finished_matches()
    return result


@shared_task
def settle_predictions():
    return settle_finished_matches()
