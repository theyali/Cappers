from decimal import Decimal, InvalidOperation

from django import template

from game.models import Prediction, PredictionCoupon

register = template.Library()


ACHIEVEMENT_DEFINITIONS = (
    {
        "key": "wins-10",
        "label": "10 побед",
        "description": "Минимум 10 выигранных прогнозов",
        "icon": "front/img/badges/wins-10.svg",
    },
    {
        "key": "roi-20",
        "label": "ROI +20%",
        "description": "Текущий ROI эксперта не ниже +20%",
        "icon": "front/img/badges/roi-20.svg",
    },
    {
        "key": "followers-100",
        "label": "100 подписчиков",
        "description": "На эксперта подписаны минимум 100 пользователей",
        "icon": "front/img/badges/followers-100.svg",
    },
    {
        "key": "streak-5",
        "label": "5 побед подряд",
        "description": "Лучшая серия эксперта — минимум 5 побед подряд",
        "icon": "front/img/badges/streak-5.svg",
    },
    {
        "key": "verified",
        "label": "Проверенный эксперт",
        "description": "Профиль эксперта подтвержден администрацией",
        "icon": "front/img/badges/verified.svg",
    },
)


def _to_decimal(value) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def build_achievement_badges(
    *,
    wins_count: int,
    overall_roi,
    followers_count: int,
    best_win_streak: int,
    is_verified: bool,
) -> list[dict]:
    conditions = {
        "wins-10": int(wins_count or 0) >= 10,
        "roi-20": _to_decimal(overall_roi) >= Decimal("20"),
        "followers-100": int(followers_count or 0) >= 100,
        "streak-5": int(best_win_streak or 0) >= 5,
        "verified": bool(is_verified),
    }
    return [
        definition
        for definition in ACHIEVEMENT_DEFINITIONS
        if conditions.get(definition["key"], False)
    ]


def _best_win_streak(expert) -> int:
    if not getattr(expert, "pk", None):
        return 0

    states = (
        Prediction.objects.filter(
            coupon__author=expert,
            coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status__in=[
                Prediction.StateStatus.WIN,
                Prediction.StateStatus.LOSE,
            ],
        )
        .order_by("updated_at", "id")
        .values_list("state_status", flat=True)
    )

    best = 0
    current = 0
    for state in states:
        if state == Prediction.StateStatus.WIN:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


@register.inclusion_tag("cabinet/_expert_achievements.html")
def expert_achievement_badges(
    expert,
    wins_count,
    overall_roi,
    followers_count,
    is_verified,
):
    badges = build_achievement_badges(
        wins_count=wins_count,
        overall_roi=overall_roi,
        followers_count=followers_count,
        best_win_streak=_best_win_streak(expert),
        is_verified=is_verified,
    )
    return {
        "achievement_badges": badges,
        "achievement_count": len(badges),
    }
