from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from .evaluators import user_achievement_metrics
from .models import (
    Achievement,
    AchievementProgressSnapshot,
    UserAchievement,
)


def _to_decimal(value) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def active_achievements_for_user(user):
    audience = (
        Achievement.Audience.ANALYST
        if getattr(user, "is_analyst", False)
        else Achievement.Audience.READER
    )
    return (
        Achievement.objects.filter(
            is_active=True,
            category__is_active=True,
        )
        .filter(
            Q(audience=Achievement.Audience.ALL)
            | Q(audience=audience)
        )
        .select_related("category")
        .order_by("category__sort_order", "sort_order", "id")
    )


def _condition_matches(achievement, current_value) -> bool:
    current = _to_decimal(current_value)
    target = _to_decimal(achievement.target_value)

    if achievement.condition_operator == Achievement.ConditionOperator.LTE:
        return current <= target
    if achievement.condition_operator == Achievement.ConditionOperator.EQ:
        return current == target
    return current >= target


def _progress_percent(achievement, current_value) -> int:
    current = _to_decimal(current_value)
    target = _to_decimal(achievement.target_value)

    if _condition_matches(achievement, current):
        return 100

    if achievement.condition_operator == Achievement.ConditionOperator.LTE:
        if current <= 0:
            return 0
        progress = target / current * Decimal("100")
    elif achievement.condition_operator == Achievement.ConditionOperator.EQ:
        if target > 0 and current >= 0:
            if current < target:
                progress = current / target * Decimal("100")
            elif current > 0:
                progress = target / current * Decimal("100")
            else:
                progress = Decimal("0")
        else:
            progress = Decimal("0")
    else:
        if target <= 0:
            return 0
        progress = current / target * Decimal("100")

    return max(0, min(99, round(float(progress))))


def _format_metric(metric: str, value) -> str:
    if metric == Achievement.Metric.ROI:
        roi = _to_decimal(value)
        prefix = "+" if roi > 0 else ""
        return f"{prefix}{roi}%"
    if metric == Achievement.Metric.VERIFIED:
        return "Получено" if _to_decimal(value) else "Не получено"
    return str(int(_to_decimal(value)))


def _icon_url(achievement) -> str:
    if not achievement.icon:
        return ""
    try:
        return achievement.icon.url
    except ValueError:
        return ""


def _serialize_achievement(
    achievement,
    *,
    current_value,
    unlocked,
    progress,
) -> dict:
    return {
        "key": achievement.key,
        "label": achievement.title,
        "title": achievement.title,
        "description": achievement.description,
        "icon": achievement.fallback_static_icon,
        "icon_url": _icon_url(achievement),
        "category": achievement.category.title,
        "metric": achievement.metric,
        "target": achievement.target_value,
        "target_value": achievement.target_value,
        "unlocked": unlocked,
        "progress": progress,
        "current_label": _format_metric(
            achievement.metric,
            current_value,
        ),
        "target_label": _format_metric(
            achievement.metric,
            achievement.target_value,
        ),
        "show_progress": achievement.show_progress,
        "is_secret": achievement.is_secret,
    }


def build_achievement_overview(
    user,
    *,
    followers_count=0,
    is_verified=False,
) -> dict:
    achievements = list(active_achievements_for_user(user))
    metrics = user_achievement_metrics(
        user,
        followers_count=followers_count,
        is_verified=is_verified,
    )

    awarded_ids = set(
        UserAchievement.objects.filter(
            user=user,
            achievement_id__in=[item.id for item in achievements],
        ).values_list("achievement_id", flat=True)
    )

    items = []
    for achievement in achievements:
        current_value = metrics.get(achievement.metric, 0)
        unlocked = (
            achievement.id in awarded_ids
            or _condition_matches(achievement, current_value)
        )
        if achievement.is_secret and not unlocked:
            continue

        progress = (
            100
            if unlocked
            else _progress_percent(achievement, current_value)
        )
        items.append(
            _serialize_achievement(
                achievement,
                current_value=current_value,
                unlocked=unlocked,
                progress=progress,
            )
        )

    unlocked_count = sum(1 for item in items if item["unlocked"])
    locked_items = [item for item in items if not item["unlocked"]]
    next_achievement = max(
        locked_items,
        key=lambda item: item["progress"],
        default=None,
    )

    return {
        "items": items,
        "unlocked_count": unlocked_count,
        "total_count": len(items),
        "completion_percent": (
            round(unlocked_count / len(items) * 100)
            if items
            else 0
        ),
        "next_achievement": next_achievement,
        "metrics": metrics,
    }


def build_achievement_badges(
    *,
    predictions_count: int,
    wins_count: int,
    overall_roi,
    followers_count: int,
    best_win_streak: int,
    is_verified: bool,
    likes_given: int = 0,
    favorites_saved: int = 0,
    referrals: int = 0,
) -> list[dict]:
    metrics = {
        "predictions": int(predictions_count or 0),
        "wins": int(wins_count or 0),
        "roi": _to_decimal(overall_roi),
        "followers": int(followers_count or 0),
        "streak": int(best_win_streak or 0),
        "verified": 1 if is_verified else 0,
        "likes_given": int(likes_given or 0),
        "favorites_saved": int(favorites_saved or 0),
        "referrals": int(referrals or 0),
    }
    achievements = (
        Achievement.objects.filter(
            is_active=True,
            category__is_active=True,
            audience__in=[
                Achievement.Audience.ALL,
                Achievement.Audience.ANALYST,
            ],
        )
        .select_related("category")
        .order_by("category__sort_order", "sort_order", "id")
    )

    badges = []
    for achievement in achievements:
        current_value = metrics.get(achievement.metric, 0)
        if not _condition_matches(achievement, current_value):
            continue
        badges.append(
            _serialize_achievement(
                achievement,
                current_value=current_value,
                unlocked=True,
                progress=100,
            )
        )
    return badges


def _award_achievement(
    user,
    achievement,
    *,
    source,
    progress_value,
    metadata,
):
    defaults = {
        "source": source,
        "progress_value": (
            achievement.target_value
            if progress_value is None
            else progress_value
        ),
        "progress_percent": 100,
        "metadata": metadata or {},
    }
    return UserAchievement.objects.get_or_create(
        user=user,
        achievement=achievement,
        defaults=defaults,
    )


@transaction.atomic
def award_achievement(
    user,
    achievement,
    *,
    source=UserAchievement.Source.AUTO,
    progress_value=None,
    metadata=None,
):
    user_achievement, _ = _award_achievement(
        user,
        achievement,
        source=source,
        progress_value=progress_value,
        metadata=metadata,
    )
    return user_achievement


def _notify_new_achievement(user, achievement) -> None:
    from notifications.models import Notification
    from notifications.services import create_notification

    url = (
        reverse(
            "front:expert_profile",
            kwargs={"username": user.username},
        )
        if getattr(user, "is_analyst", False)
        else reverse("cabinet:profile")
    )
    create_notification(
        recipient=user,
        kind=Notification.Kind.ACHIEVEMENT,
        title="Новое достижение",
        message=f"{achievement.title} — {achievement.description}",
        url=url,
        event_key=f"achievement:{user.pk}:{achievement.key}",
        meta={
            "achievement": achievement.key,
            "achievement_id": achievement.pk,
        },
    )


def _sync_progress_snapshots(user, achievements, metrics) -> None:
    now = timezone.now()
    snapshots = []
    for achievement in achievements:
        current_value = _to_decimal(metrics.get(achievement.metric, 0))
        snapshots.append(
            AchievementProgressSnapshot(
                user=user,
                achievement=achievement,
                current_value=current_value,
                progress_percent=_progress_percent(
                    achievement,
                    current_value,
                ),
                updated_at=now,
            )
        )

    if not snapshots:
        return

    AchievementProgressSnapshot.objects.bulk_create(
        snapshots,
        update_conflicts=True,
        update_fields=(
            "current_value",
            "progress_percent",
            "updated_at",
        ),
        unique_fields=("user", "achievement"),
    )


@transaction.atomic
def sync_user_achievements(
    user,
    *,
    notify=True,
) -> list[UserAchievement]:
    achievements = list(active_achievements_for_user(user))
    metrics = user_achievement_metrics(
        user,
        followers_count=None,
        is_verified=None,
    )
    _sync_progress_snapshots(user, achievements, metrics)

    existing_ids = set(
        UserAchievement.objects.filter(
            user=user,
            achievement_id__in=[item.id for item in achievements],
        ).values_list("achievement_id", flat=True)
    )

    created = []
    for achievement in achievements:
        if achievement.id in existing_ids:
            continue

        current_value = metrics.get(achievement.metric, 0)
        if not _condition_matches(achievement, current_value):
            continue

        user_achievement, was_created = _award_achievement(
            user,
            achievement,
            source=UserAchievement.Source.AUTO,
            progress_value=current_value,
            metadata=None,
        )
        if not was_created:
            continue

        created.append(user_achievement)
        if notify:
            transaction.on_commit(
                lambda achievement=achievement: _notify_new_achievement(
                    user,
                    achievement,
                )
            )

    return created
