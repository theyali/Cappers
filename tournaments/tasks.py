from celery import shared_task

from tournaments.services.leaderboard import finalize_finished_tournaments


@shared_task
def finalize_tournaments():
    return finalize_finished_tournaments()
