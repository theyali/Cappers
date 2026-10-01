from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Exists, OuterRef, QuerySet, Subquery
from django.utils import timezone


def active_vip_subscriptions(*, at=None) -> QuerySet:
    from .models import UserVipSubscription

    current_time = at or timezone.now()
    return UserVipSubscription.objects.filter(
        is_active=True,
        starts_at__lte=current_time,
        ends_at__gt=current_time,
    )


def get_active_vip(user, *, at=None):
    """Return the currently active VIP period for a user, if any."""
    if user is None or not getattr(user, "is_authenticated", False) or not getattr(user, "pk", None):
        return None

    return (
        active_vip_subscriptions(at=at)
        .filter(user_id=user.pk)
        .select_related("plan")
        .order_by("-ends_at", "-id")
        .first()
    )


def _normalize_duration_days(days) -> int:
    try:
        duration_days = int(days)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Срок VIP должен быть целым количеством дней.") from exc
    if duration_days <= 0:
        raise ValidationError("Срок VIP должен быть больше нуля.")
    return duration_days


def _validate_source(source: str) -> str:
    from .models import UserVipSubscription

    valid_sources = {value for value, _label in UserVipSubscription.Source.choices}
    if source not in valid_sources:
        raise ValidationError("Неизвестный источник VIP.")
    return source


def _create_vip_period(*, user, duration_days, source, plan=None, starts_at=None, append_existing=True):
    from .models import UserVipSubscription

    if user is None or not getattr(user, "pk", None):
        raise ValidationError("Пользователь для VIP не найден.")

    duration_days = _normalize_duration_days(duration_days)
    source = _validate_source(source)

    with transaction.atomic():
        locked_user = user.__class__.objects.select_for_update().get(pk=user.pk)
        now = timezone.now()

        # Include already scheduled continuation periods so concurrent grants are
        # always appended to the furthest active VIP tail instead of overlapping.
        vip_tail = None
        if append_existing:
            vip_tail = (
                UserVipSubscription.objects.select_for_update()
                .filter(
                    user_id=locked_user.pk,
                    is_active=True,
                    ends_at__gt=now,
                )
                .order_by("-ends_at", "-id")
                .first()
            )

        actual_starts_at = vip_tail.ends_at if vip_tail is not None else (starts_at or now)
        actual_ends_at = actual_starts_at + timedelta(days=duration_days)

        return UserVipSubscription.objects.create(
            user=locked_user,
            plan=plan,
            starts_at=actual_starts_at,
            ends_at=actual_ends_at,
            duration_days=duration_days,
            source=source,
            is_active=True,
        )


def activate_vip(user, plan, source, starts_at=None):
    """Activate a tariff, extending from the existing VIP tail when necessary."""
    from .models import VipPlan

    if plan is None or not getattr(plan, "pk", None):
        raise ValidationError("VIP-тариф не найден.")

    current_plan = VipPlan.objects.get(pk=plan.pk)
    return _create_vip_period(
        user=user,
        duration_days=current_plan.duration_days,
        source=source,
        plan=current_plan,
        starts_at=starts_at,
    )


def switch_vip(user, plan, source):
    """Replace current and scheduled VIP periods with a new tariff from now."""
    from .models import UserVipSubscription, VipPlan

    if plan is None or not getattr(plan, "pk", None):
        raise ValidationError("VIP-тариф не найден.")

    current_plan = VipPlan.objects.get(pk=plan.pk)
    now = timezone.now()
    UserVipSubscription.objects.select_for_update().filter(
        user_id=user.pk,
        is_active=True,
        ends_at__gt=now,
    ).update(is_active=False, updated_at=now)
    return _create_vip_period(
        user=user,
        duration_days=current_plan.duration_days,
        source=source,
        plan=current_plan,
        starts_at=now,
        append_existing=False,
    )


def extend_vip(user, days, source, starts_at=None):
    """Grant arbitrary VIP days through the same period-extension rules."""
    return _create_vip_period(
        user=user,
        duration_days=days,
        source=source,
        starts_at=starts_at,
    )


def purchase_vip(user, plan, *, switch=False):
    """Purchase an active VIP tariff with real balance in a single transaction."""
    from wallets.models import RealBalanceTransaction
    from wallets.services import debit_real_balance, ensure_real_balance

    from .models import UserVipSubscription, VipPlan

    if plan is None or not getattr(plan, "pk", None):
        raise ValidationError("VIP-тариф не найден.")
    if not getattr(user, "is_analyst", False):
        raise ValidationError("VIP-тарифы доступны только капперам.")

    with transaction.atomic():
        current_plan = VipPlan.objects.select_for_update().get(pk=plan.pk)
        if not current_plan.is_active:
            raise ValidationError("Этот VIP-тариф больше недоступен.")

        active_subscription = get_active_vip(user)
        if active_subscription and active_subscription.plan_id != current_plan.pk and not switch:
            raise ValidationError("Подтвердите переход на другой VIP-тариф.")

        if switch and active_subscription and active_subscription.plan_id != current_plan.pk:
            subscription = switch_vip(
                user,
                current_plan,
                UserVipSubscription.Source.PURCHASE,
            )
        else:
            subscription = activate_vip(
                user,
                current_plan,
                UserVipSubscription.Source.PURCHASE,
            )
        if current_plan.price_rub > 0:
            real_balance = debit_real_balance(
                user,
                current_plan.price_rub,
                RealBalanceTransaction.Kind.VIP_PURCHASE,
                related_obj=subscription,
                note=f"Покупка VIP «{current_plan.title}»",
            )
        else:
            real_balance = ensure_real_balance(user)
        return subscription, real_balance


def annotate_vip_status(
    queryset: QuerySet,
    *,
    user_outer_ref: str = "pk",
    at=None,
    activated_annotation_name: str = "vip_activated_at",
) -> QuerySet:
    """Attach active VIP state and dates without per-object queries."""
    active_subscriptions = active_vip_subscriptions(at=at).filter(
        user_id=OuterRef(user_outer_ref),
    )

    latest_ending = active_subscriptions.order_by("-ends_at", "-id")
    latest_activated = active_subscriptions.order_by("-starts_at", "-created_at", "-id")
    annotations = {
        "is_vip_active": Exists(active_subscriptions),
        "vip_ends_at": Subquery(latest_ending.values("ends_at")[:1]),
        activated_annotation_name: Subquery(latest_activated.values("starts_at")[:1]),
    }
    return queryset.annotate(**annotations)


def attach_vip_status_to_user(user, source) -> None:
    """Copy queryset VIP annotations from a row/card object to its related user."""
    if user is None:
        return
    user.is_vip_active = bool(getattr(source, "is_vip_active", False))
    user.vip_ends_at = getattr(source, "vip_ends_at", None)
    user.vip_activated_at = getattr(source, "vip_activated_at", None)
