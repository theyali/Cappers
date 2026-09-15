from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from game.models import Match, Prediction, PredictionCoupon

from .metrics import (
    get_match_metrics,
    get_prediction_metrics,
    refresh_match_metrics,
    refresh_match_metrics_for_coupon,
)


@receiver(post_save, sender=Match)
def ensure_match_metrics(sender, instance: Match, created: bool, **kwargs) -> None:
    if created:
        get_match_metrics(instance.pk)


@receiver(pre_save, sender=Prediction)
def remember_previous_prediction_match(sender, instance: Prediction, **kwargs) -> None:
    if not instance.pk:
        instance._metrics_previous_match_id = None
        return
    instance._metrics_previous_match_id = (
        sender.objects.filter(pk=instance.pk).values_list("match_id", flat=True).first()
    )


@receiver(post_save, sender=Prediction)
def sync_prediction_match_metrics(sender, instance: Prediction, **kwargs) -> None:
    match_ids = {instance.match_id, getattr(instance, "_metrics_previous_match_id", None)}
    for match_id in match_ids:
        if match_id:
            refresh_match_metrics(match_id)


@receiver(post_delete, sender=Prediction)
def sync_deleted_prediction_match_metrics(sender, instance: Prediction, **kwargs) -> None:
    if instance.match_id:
        refresh_match_metrics(instance.match_id)


@receiver(pre_save, sender=PredictionCoupon)
def remember_previous_coupon_visibility(sender, instance: PredictionCoupon, **kwargs) -> None:
    if not instance.pk:
        instance._metrics_previous_visibility = None
        return
    instance._metrics_previous_visibility = sender.objects.filter(pk=instance.pk).values_list(
        "published_status",
        "audience",
    ).first()


@receiver(post_save, sender=PredictionCoupon)
def sync_coupon_metrics(sender, instance: PredictionCoupon, created: bool, **kwargs) -> None:
    get_prediction_metrics(instance.pk)
    previous_visibility = getattr(instance, "_metrics_previous_visibility", None)
    current_visibility = (instance.published_status, instance.audience)
    if created or previous_visibility != current_visibility:
        refresh_match_metrics_for_coupon(instance.pk)
