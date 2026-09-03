from django.core.exceptions import ValidationError
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from cabinet.models import User
from game.models import PredictionCoupon

from .capper_bank import ensure_empty_capper_bank_stats, refresh_capper_bank_stats
from .models import CopyBettingSubscription
from .services import ensure_real_balance, ensure_virtual_balance


@receiver(pre_save, sender=CopyBettingSubscription)
def prevent_capper_copybetting(sender, instance: CopyBettingSubscription, **kwargs) -> None:
    if not instance.user_id:
        return
    if User.objects.filter(pk=instance.user_id, role=User.Role.ANALYST).exists():
        raise ValidationError("Капперы не могут использовать копибеттинг.")


@receiver(pre_save, sender=PredictionCoupon)
def remember_coupon_bank_author(sender, instance: PredictionCoupon, **kwargs) -> None:
    if not instance.pk:
        instance._bank_previous_author_id = None
        return
    instance._bank_previous_author_id = (
        PredictionCoupon.objects.filter(pk=instance.pk)
        .values_list("author_id", flat=True)
        .first()
    )


@receiver(post_save, sender=PredictionCoupon)
def sync_capper_bank_after_coupon_save(sender, instance: PredictionCoupon, **kwargs) -> None:
    if instance.author_id:
        refresh_capper_bank_stats(instance.author_id)

    previous_author_id = getattr(instance, "_bank_previous_author_id", None)
    if previous_author_id and previous_author_id != instance.author_id:
        refresh_capper_bank_stats(previous_author_id)


@receiver(post_delete, sender=PredictionCoupon)
def sync_capper_bank_after_coupon_delete(sender, instance: PredictionCoupon, **kwargs) -> None:
    if instance.author_id:
        refresh_capper_bank_stats(instance.author_id)


@receiver(post_save, sender=User)
def create_balance_for_new_user(sender, instance: User, **kwargs) -> None:
    ensure_virtual_balance(instance)
    if instance.role == User.Role.ANALYST:
        ensure_real_balance(instance)
        ensure_empty_capper_bank_stats(instance.pk)
        CopyBettingSubscription.objects.filter(user=instance).exclude(
            status=CopyBettingSubscription.Status.STOPPED,
        ).update(
            status=CopyBettingSubscription.Status.STOPPED,
            pending_status="",
            pending_status_requested_at=None,
            stopped_at=timezone.now(),
        )
