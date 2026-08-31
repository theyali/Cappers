from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Prediction, PredictionCoupon


def _sync_coupon_type(coupon_id: int | None) -> None:
    if not coupon_id:
        return
    coupon = PredictionCoupon.objects.filter(pk=coupon_id).first()
    if coupon is not None:
        coupon.sync_coupon_type()


@receiver(post_save, sender=Prediction)
def sync_coupon_type_after_prediction_save(sender, instance: Prediction, **kwargs) -> None:
    _sync_coupon_type(instance.coupon_id)


@receiver(post_delete, sender=Prediction)
def sync_coupon_type_after_prediction_delete(sender, instance: Prediction, **kwargs) -> None:
    _sync_coupon_type(instance.coupon_id)
