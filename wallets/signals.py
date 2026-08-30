from django.db.models.signals import post_save
from django.dispatch import receiver

from cabinet.models import User

from .services import ensure_capper_balance


@receiver(post_save, sender=User)
def create_balance_for_new_capper(sender, instance: User, **kwargs) -> None:
    if instance.role == User.Role.ANALYST:
        ensure_capper_balance(instance)
