from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.urls import reverse

from cabinet.models import (
    AnalystPaidSubscription,
    BonusEvent,
    ReferralBonusSettings,
    ReferralVisit,
)

from .bonus_rewards import grant_bonus_reward


REGISTRATION_BONUS_TITLE = "Реферальный бонус за регистрацию"
FIRST_TOPUP_BONUS_TITLE = "Реферальный бонус за первое пополнение"
FIRST_SUBSCRIPTION_BONUS_TITLE = "Реферальный бонус за первую подписку"


def _positive_amount(value) -> Decimal:
    try:
        amount = Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")
    if not amount.is_finite() or amount <= 0:
        return Decimal("0")
    return amount


def _registered_referral_visit_for_user(user, *, lock=False):
    if not getattr(user, "pk", None):
        return None

    visits = ReferralVisit.objects
    if lock:
        visits = visits.select_for_update()

    return (
        visits.filter(
            visitor=user,
            registered_at__isnull=False,
        )
        .exclude(referrer=user)
        .select_related("referrer", "visitor")
        .order_by("registered_at", "first_seen_at", "id")
        .first()
    )


def _has_referral_bonus(user, *, title, related_obj) -> bool:
    if related_obj is None or not getattr(related_obj, "pk", None):
        return False
    return BonusEvent.objects.filter(
        user=user,
        event_type=BonusEvent.EventType.REFERRAL,
        title=title,
        related_model=related_obj._meta.label_lower,
        related_id=related_obj.pk,
    ).exists()


@transaction.atomic
def grant_referral_registration_bonus(visit):
    if visit is None or not getattr(visit, "pk", None):
        return None

    visit = (
        ReferralVisit.objects.select_for_update()
        .select_related("referrer", "visitor")
        .filter(pk=visit.pk)
        .first()
    )
    if (
        visit is None
        or visit.visitor_id is None
        or visit.registered_at is None
        or visit.referrer_id == visit.visitor_id
    ):
        return None

    settings_obj = ReferralBonusSettings.load()
    if not settings_obj.is_enabled:
        return None

    if _has_referral_bonus(
        visit.referrer,
        title=REGISTRATION_BONUS_TITLE,
        related_obj=visit,
    ):
        return None

    if (
        settings_obj.registration_reward_coins <= 0
        and settings_obj.registration_reward_xp <= 0
    ):
        return None

    username = visit.visitor.username
    return grant_bonus_reward(
        visit.referrer,
        xp=settings_obj.registration_reward_xp,
        coins=settings_obj.registration_reward_coins,
        event_type=BonusEvent.EventType.REFERRAL,
        title=REGISTRATION_BONUS_TITLE,
        description=f"Регистрация приглашённого пользователя @{username}",
        related_obj=visit,
    )


@transaction.atomic
def grant_referral_first_topup_bonus(referred_user, amount, related_obj=None):
    topup_amount = _positive_amount(amount)
    if topup_amount <= 0:
        return None

    visit = _registered_referral_visit_for_user(referred_user, lock=True)
    if visit is None:
        return None

    settings_obj = ReferralBonusSettings.load()
    if not settings_obj.is_enabled or settings_obj.first_topup_reward_coins <= 0:
        return None

    # The referred user is the stable subject of the one-time milestone.
    # This keeps repeated calls idempotent even if the payment object changes.
    if _has_referral_bonus(
        visit.referrer,
        title=FIRST_TOPUP_BONUS_TITLE,
        related_obj=referred_user,
    ):
        return None

    description = (
        f"Первое пополнение @{referred_user.username} на {topup_amount:g}"
    )
    if related_obj is not None and getattr(related_obj, "pk", None):
        description += f" · операция #{related_obj.pk}"

    return grant_bonus_reward(
        visit.referrer,
        coins=settings_obj.first_topup_reward_coins,
        event_type=BonusEvent.EventType.REFERRAL,
        title=FIRST_TOPUP_BONUS_TITLE,
        description=description,
        related_obj=referred_user,
    )


@transaction.atomic
def grant_referral_first_subscription_bonus(referred_user, related_obj=None):
    visit = _registered_referral_visit_for_user(referred_user, lock=True)
    if visit is None:
        return None

    settings_obj = ReferralBonusSettings.load()
    if (
        not settings_obj.is_enabled
        or settings_obj.first_subscription_reward_coins <= 0
    ):
        return None

    subscriptions = AnalystPaidSubscription.objects.filter(
        subscriber=referred_user,
    ).order_by("starts_at", "id")
    subscription_ids = list(subscriptions.values_list("id", flat=True))
    if not subscription_ids:
        return None

    if BonusEvent.objects.filter(
        user=visit.referrer,
        event_type=BonusEvent.EventType.REFERRAL,
        title=FIRST_SUBSCRIPTION_BONUS_TITLE,
        related_model=AnalystPaidSubscription._meta.label_lower,
        related_id__in=subscription_ids,
    ).exists():
        return None

    subscription = None
    if (
        isinstance(related_obj, AnalystPaidSubscription)
        and related_obj.pk
        and related_obj.subscriber_id == referred_user.pk
    ):
        subscription = related_obj
    if subscription is None:
        subscription = subscriptions.first()
    if subscription is None:
        return None

    return grant_bonus_reward(
        visit.referrer,
        coins=settings_obj.first_subscription_reward_coins,
        event_type=BonusEvent.EventType.REFERRAL,
        title=FIRST_SUBSCRIPTION_BONUS_TITLE,
        description=f"Первая платная подписка @{referred_user.username}",
        related_obj=subscription,
    )


def build_referral_bonus_card(user, request=None) -> dict:
    settings_obj = ReferralBonusSettings.load()
    referral_path = reverse(
        "front:capper_referral_code",
        kwargs={
            "username": user.username,
            "code": user.referral_code,
        },
    )
    referral_url = (
        request.build_absolute_uri(referral_path)
        if request is not None
        else referral_path
    )

    return {
        "title": "Бонус за рефералов",
        "subtitle": "Приглашайте друзей",
        "reward_label": settings_obj.max_visible_reward_text,
        "description": (
            "Приглашайте друзей и получайте дополнительные бонусы на баланс."
            if settings_obj.is_enabled
            else "Реферальные бонусы временно недоступны."
        ),
        "is_enabled": settings_obj.is_enabled,
        "referral_url": referral_url,
        "referral_code": user.referral_code,
        "registration_reward_coins": settings_obj.registration_reward_coins,
        "registration_reward_xp": settings_obj.registration_reward_xp,
        "first_topup_reward_coins": settings_obj.first_topup_reward_coins,
        "first_subscription_reward_coins": settings_obj.first_subscription_reward_coins,
    }
