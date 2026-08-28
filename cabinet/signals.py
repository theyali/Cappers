from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import AnalystProfile, User


def _field_name(field) -> str:
    return field.name if field else ""


@receiver(post_save, sender=User)
def ensure_analyst_profile(sender, instance: User, **kwargs) -> None:
    """Create analyst profile when needed and keep one shared avatar for the account."""
    profile = AnalystProfile.objects.filter(user=instance).first()
    if instance.role == User.Role.ANALYST and profile is None:
        profile, _ = AnalystProfile.objects.get_or_create(user=instance)

    if profile is None:
        return

    user_avatar = _field_name(instance.avatar)
    profile_avatar = _field_name(profile.avatar)
    if user_avatar and profile_avatar != user_avatar:
        AnalystProfile.objects.filter(pk=profile.pk).update(avatar=user_avatar)
    elif profile_avatar and not user_avatar:
        User.objects.filter(pk=instance.pk).update(avatar=profile_avatar)


@receiver(post_save, sender=AnalystProfile)
def sync_capper_avatar_to_user(sender, instance: AnalystProfile, **kwargs) -> None:
    """Treat User.avatar as the account photo while keeping the legacy profile field mirrored."""
    user_avatar = _field_name(instance.user.avatar)
    profile_avatar = _field_name(instance.avatar)

    if profile_avatar and user_avatar != profile_avatar:
        User.objects.filter(pk=instance.user_id).update(avatar=profile_avatar)
    elif user_avatar and not profile_avatar:
        AnalystProfile.objects.filter(pk=instance.pk).update(avatar=user_avatar)
