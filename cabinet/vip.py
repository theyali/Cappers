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


def _create_vip_period(*, user, duration_days, source, plan=None, starts_at=None):
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


def extend_vip(user, days, source, starts_at=None):
    """Grant arbitrary VIP days through the same period-extension rules."""
    return _create_vip_period(
        user=user,
        duration_days=days,
        source=source,
        starts_at=starts_at,
    )


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
