from django.db.models.signals import post_delete, post_save, pre_save
from django.db import connection, transaction
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone

from game.models import Prediction, PredictionCoupon

from .models import (
    AnalystFollow,
    AnalystPaidSubscription,
    AnalystProfile,
    CapperMonthlyStat,
    User,
)
from .monthly_stats import monthly_stat_key, rebuild_capper_month
from .trust_index import refresh_capper_trust_index


def _profile_has_paid_predictions(profile: AnalystProfile) -> bool:
    return bool(profile.paid_predictions_enabled and profile.paid_predictions_price > 0)


def _invalidate_ranking_cache() -> None:
    from front.expert_ranking import invalidate_expert_ranking_cache

    # Invalidate immediately so reads in the same transaction/test do not reuse
    # stale data. In a real transaction invalidate once more after commit so a
    # concurrent reader cannot cache pre-commit data under the fresh generation.
    invalidate_expert_ranking_cache()
    if connection.in_atomic_block:
        transaction.on_commit(invalidate_expert_ranking_cache)


@receiver(post_save, sender=User)
def ensure_analyst_profile(sender, instance: User, **kwargs) -> None:
    """Create analyst profile when needed."""
    if instance.role == User.Role.ANALYST:
        AnalystProfile.objects.get_or_create(user=instance)


@receiver(post_save, sender=AnalystProfile)
def invalidate_capper_profile_cache(sender, instance: AnalystProfile, **kwargs) -> None:
    # Publicity, VIP/paid flags, trust index and profile card fields all feed rankings.
    _invalidate_ranking_cache()


@receiver(pre_save, sender=AnalystProfile)
def remember_previous_paid_predictions_state(sender, instance: AnalystProfile, **kwargs) -> None:
    instance._previous_paid_predictions_active = False
    if not instance.pk:
        return
    previous = sender.objects.filter(pk=instance.pk).only(
        "paid_predictions_enabled",
        "paid_predictions_price",
    ).first()
    if previous is not None:
        instance._previous_paid_predictions_active = _profile_has_paid_predictions(previous)


@receiver(post_save, sender=AnalystProfile)
def notify_followers_about_paid_predictions(sender, instance: AnalystProfile, created, **kwargs) -> None:
    if created:
        return
    was_active = bool(getattr(instance, "_previous_paid_predictions_active", False))
    is_active = _profile_has_paid_predictions(instance)
    if was_active or not is_active:
        return

    analyst = instance.user
    active_paid_subscriber_ids = set(
        AnalystPaidSubscription.objects.filter(
            analyst=analyst,
            expires_at__gt=timezone.now(),
        ).values_list("subscriber_id", flat=True)
    )
    followers = list(
        AnalystFollow.objects.filter(analyst=analyst)
        .exclude(follower_id__in=active_paid_subscriber_ids)
        .exclude(follower_id=analyst.pk)
        .select_related("follower")
    )
    if not followers:
        return

    payment_url = reverse("cabinet:paid_predictions_subscribe", args=[analyst.pk])
    price = instance.paid_predictions_price
    enabled_at = timezone.now().strftime("%Y%m%d%H%M%S")

    def send_notifications() -> None:
        from notifications.models import Notification
        from notifications.services import create_notification

        for follow in followers:
            create_notification(
                recipient=follow.follower,
                actor=analyst,
                kind=Notification.Kind.NEW_PREDICTION,
                title="Каппер стал платным",
                message=(
                    f"{instance} теперь публикует закрытые прогнозы за "
                    f"{price:.0f} ₽ в месяц. Оформите подписку, чтобы видеть их в ленте."
                ),
                url=payment_url,
                event_key=f"paid-predictions-enabled:{analyst.pk}:{follow.follower_id}:{enabled_at}",
                meta={
                    "event": "paid_predictions_enabled",
                    "analyst_id": analyst.pk,
                    "price": str(price),
                },
            )

    transaction.on_commit(send_notifications)


@receiver(pre_save, sender=PredictionCoupon)
def remember_previous_coupon_month(sender, instance: PredictionCoupon, **kwargs) -> None:
    """Remember the old bucket so edits can rebuild both the old and new month."""
    instance._monthly_stat_previous_key = None
    instance._trust_index_previous_author_id = None
    if not instance.pk:
        return
    previous = sender.objects.filter(pk=instance.pk).first()
    if previous is not None:
        instance._monthly_stat_previous_key = monthly_stat_key(previous)
        instance._trust_index_previous_author_id = previous.author_id


@receiver(post_save, sender=PredictionCoupon)
def sync_coupon_monthly_stat(sender, instance: PredictionCoupon, **kwargs) -> None:
    keys = {
        key
        for key in (
            getattr(instance, "_monthly_stat_previous_key", None),
            monthly_stat_key(instance),
        )
        if key is not None
    }
    for analyst_id, month in keys:
        rebuild_capper_month(analyst_id, month)

    analyst_ids = {instance.author_id}
    previous_author_id = getattr(instance, "_trust_index_previous_author_id", None)
    if previous_author_id:
        analyst_ids.add(previous_author_id)
    for analyst_id in analyst_ids:
        if analyst_id:
            refresh_capper_trust_index(analyst_id)

    # Published/status/stake changes affect annotations even before a month is settled.
    _invalidate_ranking_cache()


@receiver(post_delete, sender=PredictionCoupon)
def remove_coupon_from_monthly_stat(sender, instance: PredictionCoupon, **kwargs) -> None:
    key = monthly_stat_key(instance)
    if key is not None:
        rebuild_capper_month(*key)
    if instance.author_id:
        refresh_capper_trust_index(instance.author_id)
    _invalidate_ranking_cache()


def _rebuild_prediction_coupon_month(instance: Prediction) -> None:
    coupon = PredictionCoupon.objects.filter(pk=instance.coupon_id).first()
    if coupon is None:
        return
    key = monthly_stat_key(coupon)
    if key is not None:
        rebuild_capper_month(*key)


@receiver(post_save, sender=Prediction)
def sync_prediction_sport_monthly_stat(sender, instance: Prediction, **kwargs) -> None:
    """Keep the persisted per-sport split in sync when prediction items change."""
    _rebuild_prediction_coupon_month(instance)
    _invalidate_ranking_cache()


@receiver(post_delete, sender=Prediction)
def remove_prediction_from_sport_monthly_stat(sender, instance: Prediction, **kwargs) -> None:
    _rebuild_prediction_coupon_month(instance)
    _invalidate_ranking_cache()


@receiver(post_save, sender=CapperMonthlyStat)
@receiver(post_delete, sender=CapperMonthlyStat)
def invalidate_ranking_after_monthly_stat_change(sender, instance: CapperMonthlyStat, **kwargs) -> None:
    _invalidate_ranking_cache()


@receiver(post_save, sender=AnalystFollow)
@receiver(post_delete, sender=AnalystFollow)
def invalidate_ranking_after_follow_change(sender, instance: AnalystFollow, **kwargs) -> None:
    # Followers participate in the popular group and ranking tie-breakers.
    _invalidate_ranking_cache()
