from celery import shared_task

from bots.services import (
    cleanup_bot_runtime_data,
    plan_bot_tournament_activity,
    run_bot_activity,
    run_bot_planned_actions,
    run_bot_predictions,
    run_bot_presence_activity,
)


@shared_task
def run_bot_prediction_cycle():
    return run_bot_predictions()


@shared_task
def run_bot_activity_cycle():
    return run_bot_activity()


@shared_task
def run_bot_presence_activity_cycle():
    return run_bot_presence_activity()


@shared_task
def run_bot_planned_actions_cycle():
    return run_bot_planned_actions()


@shared_task
def run_bot_tournament_activity_cycle():
    return plan_bot_tournament_activity()


@shared_task
def cleanup_bot_runtime_data_cycle():
    return cleanup_bot_runtime_data()
