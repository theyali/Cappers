from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Max, Q
from django.utils import timezone

from cabinet.models import AnalystProfile, CapperMonthlyStat, User
from game.models import PredictionCoupon

from .prediction_metrics import ROI_PERIOD_DAYS, annotate_author_roi, roi_period_q


RANKING_HISTORY_PRIOR = 10
RANKING_TRUST_WEIGHT = Decimal("1000")
RANKING_STABILIZED_ROI_CAP = Decimal("25")
RANKING_ACTIVITY_MAX_BONUS = Decimal("5")
RANKING_ACTIVITY_FULL_COUNT = 50
SETTLED_EXPERT_STATES = (
    PredictionCoupon.StateStatus.WIN,
    PredictionCoupon.StateStatus.LOSE,
    PredictionCoupon.StateStatus.REFUND,
)


def current_month_start():
    today = timezone.localdate()
    return today.replace(day=1)


def current_month_top_expert_ids(limit: int = 1) -> list[int]:
    return list(
        CapperMonthlyStat.objects.filter(
            month=current_month_start(),
            bets_count__gt=0,
            analyst__role=User.Role.ANALYST,
            analyst__analyst_profile__is_public=True,
        )
        .order_by("-roi", "-bets_count", "-wins_count", "-total_profit", "analyst__username")
        .values_list("analyst_id", flat=True)[:limit]
    )


def expert_leader_badges(
    user_id,
    *,
    monthly_leader_id=None,
    all_time_leader_id=None,
) -> list[dict]:
    badges = []
    if user_id and user_id == all_time_leader_id:
        badges.append({"kind": "all-time", "label": "Лучший аналитик за все время"})
    if user_id and user_id == monthly_leader_id:
        badges.append({"kind": "month", "label": "Лучший прогнозист месяца"})
    return badges


def expert_ranking_score(profile) -> Decimal:
    """Return the canonical trust-first score used to order experts.

    The persisted trust index is the primary ranking signal. ROI is still used,
    but it is stabilised against short histories and capped so even an extreme
    ROI cannot move a profile above an expert with a higher trust index.
    Activity gives a small bonus inside the same trust-index band.
    """
    trust_index = Decimal(str(getattr(profile, "trust_index", 0) or 0))
    trust_score = trust_index * RANKING_TRUST_WEIGHT

    settled_count = int(
        getattr(profile, "roi_settled_count", getattr(profile, "settled_count", 0)) or 0
    )
    if settled_count <= 0:
        return trust_score

    roi = Decimal(str(getattr(profile, "author_roi", 0) or 0))
    stabilized_roi = (
        roi
        * Decimal(settled_count)
        / Decimal(settled_count + RANKING_HISTORY_PRIOR)
    )
    stabilized_roi_score = max(
        -RANKING_STABILIZED_ROI_CAP,
        min(RANKING_STABILIZED_ROI_CAP, stabilized_roi),
    )

    activity_count = min(settled_count, RANKING_ACTIVITY_FULL_COUNT)
    activity_bonus = (
        Decimal(activity_count)
        / Decimal(RANKING_ACTIVITY_FULL_COUNT)
        * RANKING_ACTIVITY_MAX_BONUS
    )

    # trust_index has one decimal place. A 0.1 increase is therefore +100
    # points, while all ROI/activity adjustments stay between -25 and +30.
    # This guarantees that trust_index remains the primary ranking factor.
    return trust_score + stabilized_roi_score + activity_bonus


def ranked_expert_profiles(
    *,
    limit: int | None = None,
    period_days: int | None = ROI_PERIOD_DAYS,
) -> list[AnalystProfile]:
    """Return public analysts in the canonical Cappers ranking order.

    ``trust_index`` is the primary signal. ``period_days`` controls the ROI
    calculation and settled history used only as secondary ranking signals.
    ``None`` means all available time.
    """
    recent_cutoff = timezone.now() - timedelta(days=30)
    published_filter = Q(
        user__prediction_coupons__published_status=PredictionCoupon.PublishedStatus.PUBLISHED
    )
    settled_filter = published_filter & Q(
        user__prediction_coupons__state_status__in=SETTLED_EXPERT_STATES
    )
    roi_settled_filter = settled_filter
    if period_days is not None:
        roi_settled_filter &= roi_period_q(
            prefix="user__prediction_coupons__",
            days=period_days,
        )

    queryset = (
        AnalystProfile.objects.filter(
            is_public=True,
            user__role=User.Role.ANALYST,
        )
        .select_related("user")
        .annotate(
            followers_count=Count("user__analyst_followers", distinct=True),
            publications_count=Count(
                "user__prediction_coupons",
                filter=published_filter,
                distinct=True,
            ),
            settled_count=Count(
                "user__prediction_coupons",
                filter=settled_filter,
                distinct=True,
            ),
            roi_settled_count=Count(
                "user__prediction_coupons",
                filter=roi_settled_filter,
                distinct=True,
            ),
            wins_count=Count(
                "user__prediction_coupons",
                filter=published_filter
                & Q(
                    user__prediction_coupons__state_status=PredictionCoupon.StateStatus.WIN
                ),
                distinct=True,
            ),
            losses_count=Count(
                "user__prediction_coupons",
                filter=published_filter
                & Q(
                    user__prediction_coupons__state_status=PredictionCoupon.StateStatus.LOSE
                ),
                distinct=True,
            ),
            sports_count=Count(
                "user__prediction_coupons__predictions__match__sport",
                filter=published_filter,
                distinct=True,
            ),
            recent_publications_count=Count(
                "user__prediction_coupons",
                filter=published_filter
                & Q(user__prediction_coupons__published_at__gte=recent_cutoff),
                distinct=True,
            ),
            last_publication_at=Max(
                "user__prediction_coupons__published_at",
                filter=published_filter,
            ),
        )
    )
    queryset = annotate_author_roi(
        queryset,
        author_outer_ref="user_id",
        annotation_name="author_roi",
        period_days=period_days,
    )
    profiles = list(
        annotate_author_roi(
            queryset,
            author_outer_ref="user_id",
            annotation_name="author_roi_all_time",
            period_days=None,
        )
    )

    for profile in profiles:
        profile.ranking_score = expert_ranking_score(profile)

    # Username makes exact ties deterministic. ranking_score already contains
    # trust_index as its dominant component, so it is intentionally not added
    # to the tuple a second time.
    profiles.sort(key=lambda profile: profile.user.username.lower())
    profiles.sort(
        key=lambda profile: (
            profile.ranking_score,
            profile.roi_settled_count,
            profile.settled_count,
            profile.followers_count,
            profile.publications_count,
        ),
        reverse=True,
    )

    if limit is not None:
        try:
            safe_limit = max(0, int(limit))
        except (TypeError, ValueError):
            safe_limit = 0
        return profiles[:safe_limit]
    return profiles
