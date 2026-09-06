from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.urls import reverse
from django.utils import timezone

from cabinet.models import AnalystFollow, AnalystPaidSubscription, AnalystProfile
from front.models import PredictionFavorite, PredictionLike
from wallets.models import CopyBettingSubscription

from .models import Notification
from .services import create_notification


def _display_name(user) -> str:
    try:
        profile = user.analyst_profile
    except (AnalystProfile.DoesNotExist, AttributeError):
        profile = None
    if profile and profile.display_name:
        return profile.display_name
    return user.get_full_name().strip() or user.username


def _user_profile_url(user) -> str:
    return reverse("cabinet:user_profile", kwargs={"username": user.username})


@receiver(post_save, sender=PredictionLike)
def notify_prediction_like(sender, instance: PredictionLike, created: bool, **kwargs) -> None:
    if not created or instance.prediction.author_id == instance.user_id:
        return
    create_notification(
        recipient=instance.prediction.author,
        actor=instance.user,
        kind=Notification.Kind.PREDICTION_LIKE,
        title=f"{_display_name(instance.user)} лайкнул ваш прогноз",
        message=f"Прогноз #{instance.prediction_id} получил новый лайк.",
        url=reverse("front:prediction_detail", kwargs={"prediction_id": instance.prediction_id}),
        event_key=f"prediction-like:{instance.pk}",
        meta={"prediction_id": instance.prediction_id, "actor_id": instance.user_id},
    )


@receiver(post_save, sender=PredictionFavorite)
def notify_prediction_favorite(sender, instance: PredictionFavorite, created: bool, **kwargs) -> None:
    if not created or instance.prediction.author_id == instance.user_id:
        return
    create_notification(
        recipient=instance.prediction.author,
        actor=instance.user,
        kind=Notification.Kind.PREDICTION_FAVORITE,
        title=f"{_display_name(instance.user)} сохранил ваш прогноз",
        message=f"Прогноз #{instance.prediction_id} добавили в избранное.",
        url=reverse("front:prediction_detail", kwargs={"prediction_id": instance.prediction_id}),
        event_key=f"prediction-favorite:{instance.pk}",
        meta={"prediction_id": instance.prediction_id, "actor_id": instance.user_id},
    )


@receiver(post_save, sender=AnalystFollow)
def notify_new_follower(sender, instance: AnalystFollow, created: bool, **kwargs) -> None:
    if not created or instance.follower_id == instance.analyst_id:
        return
    create_notification(
        recipient=instance.analyst,
        actor=instance.follower,
        kind=Notification.Kind.NEW_FOLLOWER,
        title=f"{_display_name(instance.follower)} подписался на вас",
        message="У вас новый подписчик.",
        url=_user_profile_url(instance.follower),
        event_key=f"new-follower:{instance.pk}",
        meta={"follower_id": instance.follower_id},
    )


@receiver(pre_save, sender=AnalystPaidSubscription)
def remember_paid_subscription_state(sender, instance: AnalystPaidSubscription, **kwargs) -> None:
    instance._notification_previous_expires_at = None
    if not instance.pk:
        return
    instance._notification_previous_expires_at = (
        sender.objects.filter(pk=instance.pk).values_list("expires_at", flat=True).first()
    )


@receiver(post_save, sender=AnalystPaidSubscription)
def notify_paid_subscription(sender, instance: AnalystPaidSubscription, created: bool, **kwargs) -> None:
    previous_expires_at = getattr(instance, "_notification_previous_expires_at", None)
    renewed = bool(
        not created
        and previous_expires_at
        and instance.expires_at
        and instance.expires_at > previous_expires_at
    )
    if not created and not renewed:
        return

    subscriber_name = _display_name(instance.subscriber)
    expires_label = timezone.localtime(instance.expires_at).strftime("%d.%m.%Y")
    create_notification(
        recipient=instance.analyst,
        actor=instance.subscriber,
        kind=Notification.Kind.PAID_SUBSCRIPTION,
        title=(
            f"{subscriber_name} купил платную подписку"
            if created
            else f"{subscriber_name} продлил платную подписку"
        ),
        message=f"Доступ к вашим платным прогнозам оплачен до {expires_label}.",
        url=reverse("cabinet:profile") + "?tab=earnings",
        event_key=f"paid-subscription:{instance.pk}:{instance.expires_at.isoformat()}",
        meta={
            "subscription_id": instance.pk,
            "subscriber_id": instance.subscriber_id,
            "expires_at": instance.expires_at.isoformat(),
            "renewed": renewed,
        },
    )


@receiver(pre_save, sender=CopyBettingSubscription)
def remember_copybetting_state(sender, instance: CopyBettingSubscription, **kwargs) -> None:
    instance._notification_previous_status = ""
    if not instance.pk:
        return
    previous = sender.objects.filter(pk=instance.pk).values("status").first()
    if previous:
        instance._notification_previous_status = previous["status"]


@receiver(post_save, sender=CopyBettingSubscription)
def notify_copybetting_activation(sender, instance: CopyBettingSubscription, created: bool, **kwargs) -> None:
    if instance.status != CopyBettingSubscription.Status.ACTIVE:
        return
    previous_status = getattr(instance, "_notification_previous_status", "")
    if not created and previous_status == CopyBettingSubscription.Status.ACTIVE:
        return

    actor_name = _display_name(instance.user)
    stamp = instance.active_since or instance.updated_at or timezone.now()
    create_notification(
        recipient=instance.analyst,
        actor=instance.user,
        kind=Notification.Kind.COPYBETTING,
        title=(
            f"{actor_name} начал копировать ваши прогнозы"
            if created
            else f"{actor_name} возобновил копибеттинг"
        ),
        message="Новые подходящие прогнозы будут автоматически копироваться пользователю.",
        url=_user_profile_url(instance.user),
        event_key=f"copybetting-active:{instance.pk}:{stamp.isoformat()}",
        meta={"copybetting_id": instance.pk, "user_id": instance.user_id},
    )
