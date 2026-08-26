from decimal import Decimal, InvalidOperation

from django import template

from game.models import Prediction, PredictionCoupon

register = template.Library()


ACHIEVEMENT_DEFINITIONS = (
    {
        "key": "first-pick",
        "label": "Первый прогноз",
        "description": "Эксперт опубликовал первый прогноз",
        "icon": "front/img/badges/first-pick.svg",
    },
    {
        "key": "predictions-5",
        "label": "5 прогнозов",
        "description": "Опубликовано минимум 5 прогнозов",
        "icon": "front/img/badges/predictions-5.svg",
    },
    {
        "key": "predictions-25",
        "label": "25 прогнозов",
        "description": "Опубликовано минимум 25 прогнозов",
        "icon": "front/img/badges/predictions-25.svg",
    },
    {
        "key": "predictions-50",
        "label": "50 прогнозов",
        "description": "Опубликовано минимум 50 прогнозов",
        "icon": "front/img/badges/predictions-50.svg",
    },
    {
        "key": "wins-3",
        "label": "3 победы",
        "description": "Минимум 3 выигранных прогноза",
        "icon": "front/img/badges/wins-3.svg",
    },
    {
        "key": "wins-10",
        "label": "10 побед",
        "description": "Минимум 10 выигранных прогнозов",
        "icon": "front/img/badges/wins-10.svg",
    },
    {
        "key": "wins-25",
        "label": "25 побед",
        "description": "Минимум 25 выигранных прогнозов",
        "icon": "front/img/badges/wins-25.svg",
    },
    {
        "key": "wins-50",
        "label": "50 побед",
        "description": "Минимум 50 выигранных прогнозов",
        "icon": "front/img/badges/wins-50.svg",
    },
    {
        "key": "roi-5",
        "label": "ROI +5%",
        "description": "Текущий ROI эксперта не ниже +5%",
        "icon": "front/img/badges/roi-5.svg",
    },
    {
        "key": "roi-10",
        "label": "ROI +10%",
        "description": "Текущий ROI эксперта не ниже +10%",
        "icon": "front/img/badges/roi-10.svg",
    },
    {
        "key": "roi-20",
        "label": "ROI +20%",
        "description": "Текущий ROI эксперта не ниже +20%",
        "icon": "front/img/badges/roi-20.svg",
    },
    {
        "key": "roi-50",
        "label": "ROI +50%",
        "description": "Текущий ROI эксперта не ниже +50%",
        "icon": "front/img/badges/roi-50.svg",
    },
    {
        "key": "followers-10",
        "label": "10 подписчиков",
        "description": "На эксперта подписаны минимум 10 пользователей",
        "icon": "front/img/badges/followers-10.svg",
    },
    {
        "key": "followers-50",
        "label": "50 подписчиков",
        "description": "На эксперта подписаны минимум 50 пользователей",
        "icon": "front/img/badges/followers-50.svg",
    },
    {
        "key": "followers-100",
        "label": "100 подписчиков",
        "description": "На эксперта подписаны минимум 100 пользователей",
        "icon": "front/img/badges/followers-100.svg",
    },
    {
        "key": "followers-250",
        "label": "250 подписчиков",
        "description": "На эксперта подписаны минимум 250 пользователей",
        "icon": "front/img/badges/followers-250.svg",
    },
    {
        "key": "streak-3",
        "label": "3 победы подряд",
        "description": "Лучшая серия эксперта — минимум 3 победы подряд",
        "icon": "front/img/badges/streak-3.svg",
    },
    {
        "key": "streak-5",
        "label": "5 побед подряд",
        "description": "Лучшая серия эксперта — минимум 5 побед подряд",
        "icon": "front/img/badges/streak-5.svg",
    },
    {
        "key": "streak-10",
        "label": "10 побед подряд",
        "description": "Лучшая серия эксперта — минимум 10 побед подряд",
        "icon": "front/img/badges/streak-10.svg",
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
    predictions_count: int,
    wins_count: int,
    overall_roi,
    followers_count: int,
    best_win_streak: int,
    is_verified: bool,
) -> list[dict]:
    predictions_count = int(predictions_count or 0)
    wins_count = int(wins_count or 0)
    followers_count = int(followers_count or 0)
    best_win_streak = int(best_win_streak or 0)
    roi = _to_decimal(overall_roi)

    conditions = {
        "first-pick": predictions_count >= 1,
        "predictions-5": predictions_count >= 5,
        "predictions-25": predictions_count >= 25,
        "predictions-50": predictions_count >= 50,
        "wins-3": wins_count >= 3,
        "wins-10": wins_count >= 10,
        "wins-25": wins_count >= 25,
        "wins-50": wins_count >= 50,
        "roi-5": roi >= Decimal("5"),
        "roi-10": roi >= Decimal("10"),
        "roi-20": roi >= Decimal("20"),
        "roi-50": roi >= Decimal("50"),
        "followers-10": followers_count >= 10,
        "followers-50": followers_count >= 50,
        "followers-100": followers_count >= 100,
        "followers-250": followers_count >= 250,
        "streak-3": best_win_streak >= 3,
        "streak-5": best_win_streak >= 5,
        "streak-10": best_win_streak >= 10,
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
    predictions_count,
    wins_count,
    overall_roi,
    followers_count,
    is_verified,
):
    badges = build_achievement_badges(
        predictions_count=predictions_count,
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
