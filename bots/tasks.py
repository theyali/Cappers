from celery import shared_task

from bots.services import run_bot_activity, run_bot_predictions


@shared_task
def run_bot_prediction_cycle():
    return run_bot_predictions()


@shared_task
def run_bot_activity_cycle():
    return run_bot_activity()
