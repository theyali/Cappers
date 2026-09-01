from django.db import transaction
from django.utils import timezone

from .models import (
    AnalystFollow,
    AnalystPaidSubscription,
    AnalystProfile,
    User,
    paid_subscription_expires_at,
)
from wallets.models import RealBalanceTransaction
from wallets.services import credit_real_balance


def profile_paid_predictions_enabled(user: User) -> bool:
    profile = getattr(user, "analyst_profile", None)
    return bool(
        profile
        and profile.paid_predictions_enabled
        and profile.paid_predictions_price > 0
    )


def user_can_view_paid_predictions(user, analyst: User) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if user.pk == analyst.pk:
        return True
    return AnalystPaidSubscription.objects.filter(
        subscriber=user,
        analyst=analyst,
        expires_at__gt=timezone.now(),
    ).exists()


def active_paid_subscription_analyst_ids(user) -> set[int]:
    if not getattr(user, "is_authenticated", False):
        return set()
    return set(
        AnalystPaidSubscription.objects.filter(
            subscriber=user,
            expires_at__gt=timezone.now(),
        ).values_list("analyst_id", flat=True)
    )


def active_paid_subscriptions_by_analyst(user, analyst_ids: list[int] | set[int]):
    if not getattr(user, "is_authenticated", False) or not analyst_ids:
        return {}
    return {
        subscription.analyst_id: subscription
        for subscription in AnalystPaidSubscription.objects.filter(
            subscriber=user,
            analyst_id__in=analyst_ids,
            expires_at__gt=timezone.now(),
        )
    }


def subscribe_to_paid_predictions(subscriber: User, analyst: User) -> AnalystPaidSubscription:
    if subscriber.pk == analyst.pk:
        raise ValueError("Нельзя оформить платную подписку на самого себя.")
    if analyst.role != User.Role.ANALYST:
        raise ValueError("Платная подписка доступна только на аналитиков.")

    profile: AnalystProfile | None = AnalystProfile.objects.filter(user=analyst).first()
    if not profile or not profile.paid_predictions_enabled or profile.paid_predictions_price <= 0:
        raise ValueError("Этот эксперт не публикует платные прогнозы.")

    now = timezone.now()
    with transaction.atomic():
        subscription, created = AnalystPaidSubscription.objects.select_for_update().get_or_create(
            subscriber=subscriber,
            analyst=analyst,
            defaults={
                "price": profile.paid_predictions_price,
                "starts_at": now,
                "expires_at": paid_subscription_expires_at(now),
            },
        )
        if created:
            AnalystFollow.objects.get_or_create(follower=subscriber, analyst=analyst)
            credit_real_balance(
                analyst,
                profile.paid_predictions_price,
                RealBalanceTransaction.Kind.SUBSCRIPTION_INCOME,
                note=f"Подписка @{subscriber.username}",
            )
            return subscription
        base_time = subscription.expires_at if subscription.expires_at > now else now
        subscription.price = profile.paid_predictions_price
        subscription.expires_at = paid_subscription_expires_at(base_time)
        if subscription.starts_at > now:
            subscription.starts_at = now
        subscription.save(update_fields=["price", "starts_at", "expires_at", "updated_at"])
        AnalystFollow.objects.get_or_create(follower=subscriber, analyst=analyst)
        credit_real_balance(
            analyst,
            profile.paid_predictions_price,
            RealBalanceTransaction.Kind.SUBSCRIPTION_INCOME,
            note=f"Продление подписки @{subscriber.username}",
        )
    return subscription
