from celery import shared_task

from wallets.services import release_held_real_income


@shared_task
def release_held_income():
    return release_held_real_income()
