from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from game.models import PredictionCoupon

from .models import AnalystProfile, User
from .monthly_stats import monthly_stat_key, rebuild_capper_month


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


@receiver(pre_save, sender=PredictionCoupon)
def remember_previous_coupon_month(sender, instance: PredictionCoupon, **kwargs) -> None:
    """Remember the old bucket so edits can rebuild both the old and new month."""
    instance._monthly_stat_previous_key = None
    if not instance.pk:
        return
    previous = sender.objects.filter(pk=instance.pk).first()
    if previous is not None:
        instance._monthly_stat_previous_key = monthly_stat_key(previous)


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


@receiver(post_delete, sender=PredictionCoupon)
def remove_coupon_from_monthly_stat(sender, instance: PredictionCoupon, **kwargs) -> None:
    key = monthly_stat_key(instance)
    if key is not None:
        rebuild_capper_month(*key)
