from django.core.exceptions import ValidationError
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from cabinet.models import User

from .models import CopyBettingSubscription
from .services import ensure_real_balance, ensure_virtual_balance


@receiver(pre_save, sender=CopyBettingSubscription)
def prevent_capper_copybetting(sender, instance: CopyBettingSubscription, **kwargs) -> None:
    if not instance.user_id:
        return
    if User.objects.filter(pk=instance.user_id, role=User.Role.ANALYST).exists():
        raise ValidationError("Капперы не могут использовать копибеттинг.")


@receiver(post_save, sender=User)
def create_balance_for_new_user(sender, instance: User, **kwargs) -> None:
    ensure_virtual_balance(instance)
    if instance.role == User.Role.ANALYST:
        ensure_real_balance(instance)
        CopyBettingSubscription.objects.filter(user=instance).exclude(
            status=CopyBettingSubscription.Status.STOPPED,
        ).update(
            status=CopyBettingSubscription.Status.STOPPED,
            stopped_at=timezone.now(),
        )
