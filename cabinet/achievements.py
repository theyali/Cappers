from decimal import Decimal, InvalidOperation

from django.db.models import Count, Q

from game.models import PredictionCoupon

from .models import CapperReferralVisit


EXPERT_ACHIEVEMENT_DEFINITIONS = (
    {"key": "first-pick", "label": "Первый прогноз", "description": "Опубликуйте первый прогноз", "icon": "front/img/badges/first-pick.svg", "metric": "predictions", "target": 1, "category": "Прогнозы"},
    {"key": "predictions-5", "label": "5 прогнозов", "description": "Опубликуйте минимум 5 прогнозов", "icon": "front/img/badges/predictions-5.svg", "metric": "predictions", "target": 5, "category": "Прогнозы"},
    {"key": "predictions-25", "label": "25 прогнозов", "description": "Опубликуйте минимум 25 прогнозов", "icon": "front/img/badges/predictions-25.svg", "metric": "predictions", "target": 25, "category": "Прогнозы"},
    {"key": "predictions-50", "label": "50 прогнозов", "description": "Опубликуйте минимум 50 прогнозов", "icon": "front/img/badges/predictions-50.svg", "metric": "predictions", "target": 50, "category": "Прогнозы"},
    {"key": "wins-3", "label": "3 победы", "description": "Выиграйте минимум 3 прогноза", "icon": "front/img/badges/wins-3.svg", "metric": "wins", "target": 3, "category": "Победы"},
    {"key": "wins-10", "label": "10 побед", "description": "Выиграйте минимум 10 прогнозов", "icon": "front/img/badges/wins-10.svg", "metric": "wins", "target": 10, "category": "Победы"},
    {"key": "wins-25", "label": "25 побед", "description": "Выиграйте минимум 25 прогнозов", "icon": "front/img/badges/wins-25.svg", "metric": "wins", "target": 25, "category": "Победы"},
    {"key": "wins-50", "label": "50 побед", "description": "Выиграйте минимум 50 прогнозов", "icon": "front/img/badges/wins-50.svg", "metric": "wins", "target": 50, "category": "Победы"},
    {"key": "roi-5", "label": "ROI +5%", "description": "Достигните текущего ROI не ниже +5%", "icon": "front/img/badges/roi-5.svg", "metric": "roi", "target": 5, "category": "ROI"},
    {"key": "roi-10", "label": "ROI +10%", "description": "Достигните текущего ROI не ниже +10%", "icon": "front/img/badges/roi-10.svg", "metric": "roi", "target": 10, "category": "ROI"},
    {"key": "roi-20", "label": "ROI +20%", "description": "Достигните текущего ROI не ниже +20%", "icon": "front/img/badges/roi-20.svg", "metric": "roi", "target": 20, "category": "ROI"},
    {"key": "roi-50", "label": "ROI +50%", "description": "Достигните текущего ROI не ниже +50%", "icon": "front/img/badges/roi-50.svg", "metric": "roi", "target": 50, "category": "ROI"},
    {"key": "followers-10", "label": "10 подписчиков", "description": "Соберите минимум 10 подписчиков", "icon": "front/img/badges/followers-10.svg", "metric": "followers", "target": 10, "category": "Аудитория"},
    {"key": "followers-50", "label": "50 подписчиков", "description": "Соберите минимум 50 подписчиков", "icon": "front/img/badges/followers-50.svg", "metric": "followers", "target": 50, "category": "Аудитория"},
    {"key": "followers-100", "label": "100 подписчиков", "description": "Соберите минимум 100 подписчиков", "icon": "front/img/badges/followers-100.svg", "metric": "followers", "target": 100, "category": "Аудитория"},
    {"key": "followers-250", "label": "250 подписчиков", "description": "Соберите минимум 250 подписчиков", "icon": "front/img/badges/followers-250.svg", "metric": "followers", "target": 250, "category": "Аудитория"},
    {"key": "streak-3", "label": "3 победы подряд", "description": "Соберите серию минимум из 3 побед подряд", "icon": "front/img/badges/streak-3.svg", "metric": "streak", "target": 3, "category": "Серии"},
    {"key": "streak-5", "label": "5 побед подряд", "description": "Соберите серию минимум из 5 побед подряд", "icon": "front/img/badges/streak-5.svg", "metric": "streak", "target": 5, "category": "Серии"},
    {"key": "streak-10", "label": "10 побед подряд", "description": "Соберите серию минимум из 10 побед подряд", "icon": "front/img/badges/streak-10.svg", "metric": "streak", "target": 10, "category": "Серии"},
    {"key": "verified", "label": "Проверенный эксперт", "description": "Получите подтверждение профиля администрацией", "icon": "front/img/badges/verified.svg", "metric": "verified", "target": 1, "category": "Статус"},
)

REFERRAL_ACHIEVEMENT_DEFINITIONS = (
    {"key": "referrals-5", "label": "Первые 5 рефералов", "description": "Приведите 5 пользователей, которые подпишутся на вас по реферальной ссылке", "icon": "front/img/badges/referrals.svg", "metric": "referrals", "target": 5, "category": "Рефералы"},
    {"key": "referrals-10", "label": "10 рефералов", "description": "Получите 10 подписок после перехода по вашей реферальной ссылке", "icon": "front/img/badges/referrals.svg", "metric": "referrals", "target": 10, "category": "Рефералы"},
    {"key": "referrals-25", "label": "25 рефералов", "description": "Получите 25 подписок после перехода по вашей реферальной ссылке", "icon": "front/img/badges/referrals.svg", "metric": "referrals", "target": 25, "category": "Рефералы"},
    {"key": "referrals-50", "label": "50 рефералов", "description": "Получите 50 подписок после перехода по вашей реферальной ссылке", "icon": "front/img/badges/referrals.svg", "metric": "referrals", "target": 50, "category": "Рефералы"},
)

USER_ACTIVITY_ACHIEVEMENT_DEFINITIONS = (
    {"key": "likes-5", "label": "5 лайков", "description": "Поставьте лайк 5 прогнозам", "icon": "front/img/badges/likes.svg", "metric": "likes_given", "target": 5, "category": "Активность"},
    {"key": "likes-10", "label": "10 лайков", "description": "Поставьте лайк 10 прогнозам", "icon": "front/img/badges/likes.svg", "metric": "likes_given", "target": 10, "category": "Активность"},
    {"key": "likes-25", "label": "25 лайков", "description": "Поставьте лайк 25 прогнозам", "icon": "front/img/badges/likes.svg", "metric": "likes_given", "target": 25, "category": "Активность"},
    {"key": "likes-50", "label": "50 лайков", "description": "Поставьте лайк 50 прогнозам", "icon": "front/img/badges/likes.svg", "metric": "likes_given", "target": 50, "category": "Активность"},
    {"key": "favorites-5", "label": "5 сохранений", "description": "Сохраните 5 прогнозов в избранное", "icon": "front/img/badges/favorites.svg", "metric": "favorites_saved", "target": 5, "category": "Активность"},
    {"key": "favorites-10", "label": "10 сохранений", "description": "Сохраните 10 прогнозов в избранное", "icon": "front/img/badges/favorites.svg", "metric": "favorites_saved", "target": 10, "category": "Активность"},
    {"key": "favorites-25", "label": "25 сохранений", "description": "Сохраните 25 прогнозов в избранное", "icon": "front/img/badges/favorites.svg", "metric": "favorites_saved", "target": 25, "category": "Активность"},
    {"key": "favorites-50", "label": "50 сохранений", "description": "Сохраните 50 прогнозов в избранное", "icon": "front/img/badges/favorites.svg", "metric": "favorites_saved", "target": 50, "category": "Активность"},
)

ACHIEVEMENT_DEFINITIONS = (
    EXPERT_ACHIEVEMENT_DEFINITIONS
    + REFERRAL_ACHIEVEMENT_DEFINITIONS
    + USER_ACTIVITY_ACHIEVEMENT_DEFINITIONS
)


def _to_decimal(value) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _best_win_streak(expert) -> int:
    if not getattr(expert, "pk", None):
        return 0

    states = (
        PredictionCoupon.objects.filter(
            author=expert,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status__in=[
                PredictionCoupon.StateStatus.WIN,
                PredictionCoupon.StateStatus.LOSE,
            ],
        )
        .order_by("settled_at", "updated_at", "id")
        .values_list("state_status", flat=True)
    )

    best = 0
    current = 0
    for state in states:
        if state == PredictionCoupon.StateStatus.WIN:
            current += 1
            best = max(best, current)
        else:
            current = 0
    return best


def _published_predictions_count(expert) -> int:
    if not getattr(expert, "pk", None):
        return 0
    return PredictionCoupon.objects.filter(
        author=expert,
        published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
    ).count()


def _overall_roi(expert) -> Decimal:
    coupons = PredictionCoupon.objects.filter(
        author=expert,
        published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        state_status__in=[
            PredictionCoupon.StateStatus.WIN,
            PredictionCoupon.StateStatus.LOSE,
            PredictionCoupon.StateStatus.REFUND,
        ],
        total_stake__gt=0,
    ).values("state_status", "total_stake", "possible_payout")

    total_stake = Decimal("0")
    profit = Decimal("0")
    for coupon in coupons:
        stake = _to_decimal(coupon["total_stake"])
        payout = _to_decimal(coupon["possible_payout"])
        total_stake += stake
        if coupon["state_status"] == PredictionCoupon.StateStatus.WIN:
            profit += payout - stake
        elif coupon["state_status"] == PredictionCoupon.StateStatus.LOSE:
            profit -= stake

    if not total_stake:
        return Decimal("0")
    return (profit / total_stake * Decimal("100")).quantize(Decimal("0.1"))


def _user_activity_metrics(user) -> dict:
    if not getattr(user, "pk", None):
        return {"likes_given": 0, "favorites_saved": 0, "referrals": 0}

    likes_given = user.prediction_likes.count()
    favorites_saved = user.prediction_favorites.count()
    referrals = 0
    if getattr(user, "is_analyst", False):
        referrals = (
            CapperReferralVisit.objects.filter(
                analyst=user,
                subscribed_at__isnull=False,
                visitor__isnull=False,
            )
            .values("visitor_id")
            .distinct()
            .count()
        )
    return {
        "likes_given": likes_given,
        "favorites_saved": favorites_saved,
        "referrals": referrals,
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
    return [
        definition
        for definition in ACHIEVEMENT_DEFINITIONS
        if _to_decimal(metrics[definition["metric"]]) >= _to_decimal(definition["target"])
    ]


def _format_metric(metric: str, value) -> str:
    if metric == "roi":
        roi = _to_decimal(value)
        prefix = "+" if roi > 0 else ""
        return f"{prefix}{roi}%"
    if metric == "verified":
        return "Получено" if value else "Не получено"
    return str(int(value or 0))


def build_achievement_overview(user, *, followers_count: int = 0, is_verified: bool = False) -> dict:
    is_expert = bool(getattr(user, "is_analyst", False))
    if is_expert:
        published = PredictionCoupon.objects.filter(
            author=user,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        )
        stats = published.aggregate(
            predictions=Count("id"),
            wins=Count("id", filter=Q(state_status=PredictionCoupon.StateStatus.WIN)),
        )
    else:
        stats = {"predictions": 0, "wins": 0}

    activity_metrics = _user_activity_metrics(user)
    metrics = {
        "predictions": stats["predictions"] or 0,
        "wins": stats["wins"] or 0,
        "roi": _overall_roi(user) if is_expert else Decimal("0"),
        "followers": int(followers_count or 0),
        "streak": _best_win_streak(user) if is_expert else 0,
        "verified": 1 if is_verified else 0,
        **activity_metrics,
    }

    definitions = USER_ACTIVITY_ACHIEVEMENT_DEFINITIONS
    if is_expert:
        definitions = (
            EXPERT_ACHIEVEMENT_DEFINITIONS
            + REFERRAL_ACHIEVEMENT_DEFINITIONS
            + USER_ACTIVITY_ACHIEVEMENT_DEFINITIONS
        )

    items = []
    for definition in definitions:
        metric = definition["metric"]
        current = _to_decimal(metrics[metric])
        target = _to_decimal(definition["target"])
        unlocked = current >= target
        progress = 100 if unlocked else max(0, min(99, round(float(current / target * 100)))) if target else 0
        item = dict(definition)
        item.update(
            {
                "unlocked": unlocked,
                "progress": progress,
                "current_label": _format_metric(metric, metrics[metric]),
                "target_label": _format_metric(metric, definition["target"]),
            }
        )
        items.append(item)

    unlocked_count = sum(1 for item in items if item["unlocked"])
    locked = [item for item in items if not item["unlocked"]]
    next_achievement = max(locked, key=lambda item: item["progress"], default=None)
    return {
        "items": items,
        "unlocked_count": unlocked_count,
        "total_count": len(items),
        "completion_percent": round(unlocked_count / len(items) * 100) if items else 0,
        "next_achievement": next_achievement,
        "metrics": metrics,
    }
