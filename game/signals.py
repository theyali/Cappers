from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .cover_images import assign_coupon_cover_image, invalidate_cover_ids_cache
from .models import Prediction, PredictionCoupon, PredictionCoverImage


def _sync_coupon_type(coupon_id: int | None) -> None:
    if not coupon_id:
        return
    coupon = PredictionCoupon.objects.filter(pk=coupon_id).first()
    if coupon is not None:
        coupon.sync_coupon_type()
        if coupon.published_status == PredictionCoupon.PublishedStatus.PUBLISHED:
            assign_coupon_cover_image(coupon)


@receiver(post_save, sender=PredictionCoupon)
def assign_cover_after_coupon_publish(sender, instance: PredictionCoupon, **kwargs) -> None:
    if instance.published_status == PredictionCoupon.PublishedStatus.PUBLISHED:
        assign_coupon_cover_image(instance)


@receiver(post_save, sender=Prediction)
def sync_coupon_type_after_prediction_save(sender, instance: Prediction, **kwargs) -> None:
    _sync_coupon_type(instance.coupon_id)


@receiver(post_delete, sender=Prediction)
def sync_coupon_type_after_prediction_delete(sender, instance: Prediction, **kwargs) -> None:
    _sync_coupon_type(instance.coupon_id)


@receiver(post_save, sender=PredictionCoverImage)
@receiver(post_delete, sender=PredictionCoverImage)
def invalidate_prediction_cover_cache(sender, instance: PredictionCoverImage, **kwargs) -> None:
    invalidate_cover_ids_cache()
