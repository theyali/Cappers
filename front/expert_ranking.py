from datetime import timedelta
from decimal import Decimal

from django.db.models import Count, Max, Q
from django.utils import timezone

from cabinet.models import AnalystProfile, User
from game.models import PredictionCoupon

from .prediction_metrics import annotate_author_roi


RANKING_HISTORY_PRIOR = 10
SETTLED_EXPERT_STATES = (
    PredictionCoupon.StateStatus.WIN,
    PredictionCoupon.StateStatus.LOSE,
    PredictionCoupon.StateStatus.REFUND,
)


def expert_ranking_score(profile) -> Decimal:
    """Return the single ranking score used everywhere experts are ordered.

    Raw ROI is shrunk toward zero for experts with a short result history so a
    single lucky coupon cannot immediately put a new profile at the top.
    """
    settled_count = int(getattr(profile, "settled_count", 0) or 0)
    if settled_count <= 0:
        return Decimal("0")

    roi = Decimal(getattr(profile, "author_roi", 0) or 0)
    return (
        roi
        * Decimal(settled_count)
        / Decimal(settled_count + RANKING_HISTORY_PRIOR)
    )


def ranked_expert_profiles(*, limit: int | None = None) -> list[AnalystProfile]:
    """Return public analysts in the canonical Cappers ranking order.

    Any page that displays ranked experts must use this function instead of
    defining its own ``order_by`` rules.
    """
    recent_cutoff = timezone.now() - timedelta(days=30)
    published_filter = Q(
        user__prediction_coupons__published_status=PredictionCoupon.PublishedStatus.PUBLISHED
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
                filter=published_filter
                & Q(
                    user__prediction_coupons__state_status__in=SETTLED_EXPERT_STATES
                ),
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
    profiles = list(
        annotate_author_roi(
            queryset,
            author_outer_ref="user_id",
            annotation_name="author_roi",
        )
    )

    for profile in profiles:
        profile.ranking_score = expert_ranking_score(profile)

    # Username makes exact ties deterministic. The second stable sort applies
    # the actual ranking rule shared by the catalog and the home page.
    profiles.sort(key=lambda profile: profile.user.username.lower())
    profiles.sort(
        key=lambda profile: (
            1 if profile.settled_count else 0,
            profile.ranking_score,
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
