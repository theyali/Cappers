from decimal import Decimal, InvalidOperation

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Case, Count, DecimalField, F, Q, Sum, Value, When
from django.db.models.functions import Coalesce

from cabinet.models import ReferralVisit
from game.models import PredictionCoupon


def _to_decimal(value) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _best_win_streak(user) -> int:
    states = (
        PredictionCoupon.objects.filter(
            author=user,
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


def user_achievement_metrics(
    user,
    *,
    followers_count=None,
    is_verified=None,
) -> dict:
    if not getattr(user, "pk", None):
        return {
            "predictions": 0,
            "wins": 0,
            "roi": Decimal("0"),
            "followers": int(followers_count or 0),
            "streak": 0,
            "verified": 1 if is_verified else 0,
            "likes_given": 0,
            "favorites_saved": 0,
            "referrals": 0,
        }

    is_analyst = bool(getattr(user, "is_analyst", False))
    predictions = 0
    wins = 0
    roi = Decimal("0")
    streak = 0
    referrals = 0

    if is_analyst:
        published = PredictionCoupon.objects.filter(
            author=user,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        )
        settled_filter = Q(
            state_status__in=[
                PredictionCoupon.StateStatus.WIN,
                PredictionCoupon.StateStatus.LOSE,
                PredictionCoupon.StateStatus.REFUND,
            ],
            total_stake__gt=0,
        )
        profit_expression = Case(
            When(
                state_status=PredictionCoupon.StateStatus.WIN,
                total_stake__gt=0,
                then=(
                    Coalesce(
                        F("possible_payout"),
                        Value(Decimal("0")),
                    )
                    - F("total_stake")
                ),
            ),
            When(
                state_status=PredictionCoupon.StateStatus.LOSE,
                total_stake__gt=0,
                then=-F("total_stake"),
            ),
            default=Value(Decimal("0")),
            output_field=DecimalField(max_digits=20, decimal_places=2),
        )
        stats = published.aggregate(
            predictions=Count("id"),
            wins=Count(
                "id",
                filter=Q(state_status=PredictionCoupon.StateStatus.WIN),
            ),
            roi_stake=Sum(
                "total_stake",
                filter=settled_filter,
                default=Decimal("0"),
            ),
            roi_profit=Sum(
                profit_expression,
                default=Decimal("0"),
            ),
        )
        predictions = int(stats["predictions"] or 0)
        wins = int(stats["wins"] or 0)
        roi_stake = _to_decimal(stats["roi_stake"])
        if roi_stake:
            roi = (
                _to_decimal(stats["roi_profit"])
                / roi_stake
                * Decimal("100")
            ).quantize(Decimal("0.1"))

        streak = _best_win_streak(user)
        referrals = (
            ReferralVisit.objects.filter(
                referrer=user,
                subscribed_at__isnull=False,
                visitor__isnull=False,
            )
            .values("visitor_id")
            .distinct()
            .count()
        )

    if followers_count is None:
        followers_count = (
            user.analyst_followers.count()
            if is_analyst
            else 0
        )

    if is_verified is None:
        is_verified = False
        if is_analyst:
            try:
                is_verified = bool(user.analyst_profile.is_verified)
            except ObjectDoesNotExist:
                pass

    return {
        "predictions": predictions,
        "wins": wins,
        "roi": roi,
        "followers": int(followers_count or 0),
        "streak": streak,
        "verified": 1 if is_verified else 0,
        "likes_given": user.prediction_likes.count(),
        "favorites_saved": user.prediction_favorites.count(),
        "referrals": referrals,
    }
