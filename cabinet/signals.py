from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import AnalystProfile, User


@receiver(post_save, sender=User)
def ensure_analyst_profile(sender, instance: User, **kwargs) -> None:
    """Create an analyst profile whenever a user has the analyst role."""
    if instance.role == User.Role.ANALYST:
        AnalystProfile.objects.get_or_create(user=instance)
