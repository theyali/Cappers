from celery import shared_task


@shared_task
def refresh_expert_rankings_task(periods=None):
    from .expert_ranking import refresh_core_expert_rankings

    refresh_core_expert_rankings(periods=list(periods or ()))
