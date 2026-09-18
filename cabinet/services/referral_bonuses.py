from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone

from wallets.models import RealBalanceTransaction
from wallets.services import format_money

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
    registrations_count = (
        ReferralVisit.objects.filter(
            referrer=user,
            registered_at__isnull=False,
            visitor__isnull=False,
        )
        .values("visitor_id")
        .distinct()
        .count()
    )

    return {
        "title": "Бонус за рефералов",
        "subtitle": f"Приглашено: {registrations_count}",
        "reward_label": settings_obj.max_visible_reward_text,
        "description": (
            "Приглашайте друзей и получайте дополнительные бонусы на баланс."
            if settings_obj.is_enabled
            else "Реферальные бонусы временно недоступны."
        ),
        "is_enabled": settings_obj.is_enabled,
        "referral_url": referral_url,
        "referral_code": user.referral_code,
        "registrations_count": registrations_count,
        "link_label": "Открыть реферальную ссылку",
        "registration_reward_coins": settings_obj.registration_reward_coins,
        "registration_reward_xp": settings_obj.registration_reward_xp,
        "first_topup_reward_coins": settings_obj.first_topup_reward_coins,
        "first_subscription_reward_coins": settings_obj.first_subscription_reward_coins,
    }

def _referral_datetime_label(value) -> str:
    if value is None:
        return ""
    return timezone.localtime(value).strftime("%d.%m.%Y, %H:%M")


def _referral_event_context(event) -> dict:
    rewards = []
    if event.coin_delta:
        rewards.append(f"{event.coin_delta:+d} монет")
    if event.xp_delta:
        rewards.append(f"{event.xp_delta:+d} XP")
    if event.spin_delta:
        rewards.append(f"{event.spin_delta:+d} попыток")

    return {
        "title": event.title,
        "description": event.description,
        "reward_label": " · ".join(rewards),
        "created_at_label": _referral_datetime_label(event.created_at),
    }


def build_referrals_page_context(user, request=None) -> dict:
    """Build referral statistics and rewards for SSR and the legacy JSON endpoint."""
    visits = ReferralVisit.objects.filter(referrer=user)
    authenticated_visitors = (
        visits.filter(visitor__isnull=False)
        .values("visitor_id")
        .distinct()
        .count()
    )
    anonymous_visitors = visits.filter(visitor__isnull=True).count()
    visitors_count = authenticated_visitors + anonymous_visitors
    clicks_count = visits.aggregate(total=Sum("visits_count"))["total"] or 0
    registrations_count = (
        visits.filter(
            registered_at__isnull=False,
            visitor__isnull=False,
        )
        .values("visitor_id")
        .distinct()
        .count()
    )
    subscriptions_count = (
        visits.filter(
            subscribed_at__isnull=False,
            visitor__isnull=False,
        )
        .values("visitor_id")
        .distinct()
        .count()
    )
    conversion = (
        round(registrations_count / visitors_count * 100, 1)
        if visitors_count
        else 0
    )

    recent_visits = []
    for visit in visits.select_related("visitor")[:40]:
        visitor = visit.visitor
        registered = visit.registered_at is not None
        subscribed = visit.subscribed_at is not None

        if subscribed:
            status = "subscribed"
            status_label = "Подписался"
        elif registered:
            status = "registered"
            status_label = "Зарегистрировался"
        else:
            status = "visited"
            status_label = "Перешёл по ссылке"

        recent_visits.append(
            {
                "username": visitor.username if visitor else "",
                "name": (
                    visitor.get_full_name().strip() or visitor.username
                    if visitor
                    else "Неавторизованный посетитель"
                ),
                "visits_count": visit.visits_count,
                "first_seen_label": _referral_datetime_label(visit.first_seen_at),
                "last_seen_label": _referral_datetime_label(visit.last_seen_at),
                "registered": registered,
                "registered_label": (
                    _referral_datetime_label(visit.registered_at)
                    if registered
                    else "Нет"
                ),
                "subscribed": subscribed,
                "subscribed_label": (
                    _referral_datetime_label(visit.subscribed_at)
                    if subscribed
                    else "Нет"
                ),
                "status": status,
                "status_label": status_label,
                "first_seen_at": visit.first_seen_at.isoformat(),
                "last_seen_at": visit.last_seen_at.isoformat(),
                "registered_at": (
                    visit.registered_at.isoformat()
                    if visit.registered_at
                    else ""
                ),
                "subscribed_at": (
                    visit.subscribed_at.isoformat()
                    if visit.subscribed_at
                    else ""
                ),
            }
        )

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

    referral_income = 0
    if user.is_analyst:
        referral_income = (
            RealBalanceTransaction.objects.filter(
                user=user,
                status=RealBalanceTransaction.Status.COMPLETED,
                amount__gt=0,
                kind__in=[
                    RealBalanceTransaction.Kind.REFERRAL_SUBSCRIPTION,
                    RealBalanceTransaction.Kind.REFERRAL_TOURNAMENT,
                    RealBalanceTransaction.Kind.REFERRAL_BALANCE_TOP_UP,
                ],
            ).aggregate(total=Sum("amount"))["total"]
            or 0
        )

    settings_obj = ReferralBonusSettings.load()
    bonus_settings = {
        "is_enabled": settings_obj.is_enabled,
        "registration_reward_coins": settings_obj.registration_reward_coins,
        "registration_reward_xp": settings_obj.registration_reward_xp,
        "first_topup_reward_coins": settings_obj.first_topup_reward_coins,
        "first_subscription_reward_coins": (
            settings_obj.first_subscription_reward_coins
        ),
        "max_visible_reward_text": settings_obj.max_visible_reward_text,
    }
    registration_rewards = []
    if settings_obj.registration_reward_coins:
        registration_rewards.append(
            f"+{settings_obj.registration_reward_coins} монет"
        )
    if settings_obj.registration_reward_xp:
        registration_rewards.append(
            f"+{settings_obj.registration_reward_xp} XP"
        )

    bonus_cards = [
        {
            "key": "registration",
            "title": "За регистрацию",
            "description": "Друг зарегистрировался по вашей ссылке.",
            "reward_label": " · ".join(registration_rewards) or "Без награды",
        },
        {
            "key": "first_topup",
            "title": "За первое пополнение",
            "description": "Друг впервые пополнил баланс.",
            "reward_label": (
                f"+{settings_obj.first_topup_reward_coins} монет"
                if settings_obj.first_topup_reward_coins
                else "Без награды"
            ),
        },
        {
            "key": "first_subscription",
            "title": "За первую подписку",
            "description": "Друг впервые оформил платную подписку.",
            "reward_label": (
                f"+{settings_obj.first_subscription_reward_coins} монет"
                if settings_obj.first_subscription_reward_coins
                else "Без награды"
            ),
        },
    ]

    recent_bonus_events = [
        _referral_event_context(event)
        for event in BonusEvent.objects.filter(
            user=user,
            event_type=BonusEvent.EventType.REFERRAL,
        ).order_by("-created_at", "-id")[:40]
    ]

    return {
        "page": {
            "title": "Рефералы — КапперХаб",
            "heading": "Рефералы",
            "description": (
                "Приглашайте пользователей по своей ссылке и следите "
                "за переходами, регистрациями и бонусами."
            ),
            "mobile_nav_label": "Разделы профиля на мобильных устройствах",
            "profile_nav_label": "Разделы профиля",
        },
        "referral_url": referral_url,
        "referral_code": user.referral_code,
        "can_earn_referrals": user.is_analyst,
        "referral_income_display": format_money(referral_income),
        "visitors_count": visitors_count,
        "clicks_count": clicks_count,
        "registrations_count": registrations_count,
        "subscriptions_count": subscriptions_count,
        "conversion": conversion,
        "bonus_settings": bonus_settings,
        "bonus_cards": bonus_cards,
        "recent_visits": recent_visits,
        "recent_bonus_events": recent_bonus_events,
    }

