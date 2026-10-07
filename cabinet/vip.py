from datetime import timedelta
from decimal import Decimal

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


def _create_vip_period(*, user, duration_days, source, plan=None, starts_at=None, append_existing=True, payment=None):
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
            payment=payment,
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


def plural_ru(value: int, one: str, few: str, many: str) -> str:
    value = abs(int(value))
    if value % 10 == 1 and value % 100 != 11:
        return one
    if 2 <= value % 10 <= 4 and not 12 <= value % 100 <= 14:
        return few
    return many


def vip_switch_warning(user, *, at=None) -> str:
    """What a tariff switch burns: unused VIP time and the money paid for it."""
    from wallets.models import RealBalanceTransaction
    from wallets.services import format_money

    from .models import UserVipSubscription

    now = at or timezone.now()
    periods = list(UserVipSubscription.objects.filter(user_id=user.pk, is_active=True, ends_at__gt=now))
    if not periods:
        return ""
    paid_by_period = dict(
        RealBalanceTransaction.objects.filter(
            user_id=user.pk,
            kind=RealBalanceTransaction.Kind.VIP_PURCHASE,
            related_model=UserVipSubscription._meta.label_lower,
            related_id__in=[period.pk for period in periods],
        ).values_list("related_id", "amount")
    )
    unused = timedelta()
    lost_money = Decimal("0")
    for period in periods:
        period_unused = period.ends_at - max(period.starts_at, now)
        unused += period_unused
        paid = abs(paid_by_period.get(period.pk) or 0)
        period_length = period.ends_at - period.starts_at
        if paid and period_length.total_seconds() > 0:
            lost_money += paid * Decimal(period_unused.total_seconds() / period_length.total_seconds())

    if unused >= timedelta(days=1):
        days = round(unused.total_seconds() / 86400)
        unused_label = f"{days} {plural_ru(days, 'день', 'дня', 'дней')}"
    else:
        hours = max(1, int(unused.total_seconds() // 3600))
        unused_label = f"{hours} {plural_ru(hours, 'час', 'часа', 'часов')}"
    if lost_money >= 1:
        return (
            f"Неиспользованные {unused_label} текущего VIP сгорят. "
            f"Из них оплачено примерно {format_money(lost_money.quantize(Decimal('1')))} ₽, эти деньги не возвращаются."
        )
    return f"Неиспользованные {unused_label} текущего VIP сгорят без возврата."


def grant_paid_vip(user, plan, *, duration_days, switch, provider_payment=None):
    """Give a bought VIP period on the terms it was paid for.

    With a confirmed ``switch`` to another tariff the current and scheduled
    periods end and the new one starts now; otherwise it follows the VIP tail.
    ``plan`` may be None when the tariff was deleted after the payment.
    """
    from .models import UserVipSubscription

    source = UserVipSubscription.Source.PURCHASE
    active_subscription = get_active_vip(user)
    if switch and active_subscription and active_subscription.plan_id != getattr(plan, "pk", None):
        now = timezone.now()
        UserVipSubscription.objects.filter(
            user_id=user.pk,
            is_active=True,
            ends_at__gt=now,
        ).update(is_active=False, updated_at=now)
        return _create_vip_period(
            user=user,
            duration_days=duration_days,
            source=source,
            plan=plan,
            starts_at=now,
            append_existing=False,
            payment=provider_payment,
        )
    return _create_vip_period(
        user=user,
        duration_days=duration_days,
        source=source,
        plan=plan,
        payment=provider_payment,
    )


def extend_vip(user, days, source, starts_at=None):
    """Grant arbitrary VIP days through the same period-extension rules."""
    return _create_vip_period(
        user=user,
        duration_days=days,
        source=source,
        starts_at=starts_at,
    )


def validate_vip_purchase(user, plan, *, switch: bool) -> None:
    """Raise ValidationError unless ``user`` may buy ``plan`` now."""
    if not getattr(user, "is_analyst", False):
        raise ValidationError("VIP-тарифы доступны только капперам.")
    if not plan.is_active:
        raise ValidationError("Этот VIP-тариф больше недоступен.")
    active_subscription = get_active_vip(user)
    if active_subscription and active_subscription.plan_id != plan.pk and not switch:
        raise ValidationError(f"{vip_switch_warning(user)} Подтвердите переход на другой VIP-тариф.")


def purchase_vip(user, plan, *, switch=False):
    """Purchase an active VIP tariff with real balance in a single transaction."""
    from wallets.models import RealBalanceTransaction
    from wallets.services import debit_real_balance, ensure_real_balance

    from .models import VipPlan

    if plan is None or not getattr(plan, "pk", None):
        raise ValidationError("VIP-тариф не найден.")

    with transaction.atomic():
        current_plan = VipPlan.objects.select_for_update().get(pk=plan.pk)
        validate_vip_purchase(user, current_plan, switch=switch)

        subscription = grant_paid_vip(
            user,
            current_plan,
            duration_days=current_plan.duration_days,
            switch=switch,
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
