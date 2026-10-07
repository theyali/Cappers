from celery import shared_task

from game.models import PredictionCoupon
from wallets.services import copy_published_coupon, release_held_real_income


@shared_task
def release_held_income():
    return release_held_real_income()


@shared_task
def copy_coupon_to_followers(coupon_id: int) -> int:
    coupon = PredictionCoupon.objects.select_related("author").filter(pk=coupon_id).first()
    if coupon is None:
        return 0
    return len(copy_published_coupon(coupon))
