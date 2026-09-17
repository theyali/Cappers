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
