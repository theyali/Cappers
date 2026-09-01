from django.db.models.signals import post_save
from django.dispatch import receiver

from cabinet.models import User

from .services import ensure_real_balance, ensure_virtual_balance


@receiver(post_save, sender=User)
def create_balance_for_new_user(sender, instance: User, **kwargs) -> None:
    ensure_virtual_balance(instance)
    if instance.role == User.Role.ANALYST:
        ensure_real_balance(instance)
