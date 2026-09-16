from django.db.models import Count, Exists, OuterRef, Q
from django.db.models.functions import Coalesce
from django.urls import reverse

from cabinet.models import AnalystFollow, AnalystProfile, User
from game.models import PredictionCoupon


DEFAULT_VIP_CAPPERS_LIMIT = 6
MAX_VIP_CAPPERS_LIMIT = 12


def _normalize_limit(limit) -> int:
    try:
        return max(1, min(int(limit), MAX_VIP_CAPPERS_LIMIT))
    except (TypeError, ValueError):
        return DEFAULT_VIP_CAPPERS_LIMIT


def _main_sport_category(profile: AnalystProfile) -> str:
    sports = (profile.favorite_sports or "").replace(";", ",")
    main_sport = next(
        (item.strip() for item in sports.split(",") if item.strip()),
        "",
    )
    category = (profile.specialization or "").strip()

    parts = []
    for value in (main_sport, category):
        if value and value not in parts:
            parts.append(value)
    return " · ".join(parts) or "Спортивные прогнозы"


def _card_payload(profile: AnalystProfile) -> dict:
    wins_count = int(getattr(profile, "wins_count", 0) or 0)
    losses_count = int(getattr(profile, "losses_count", 0) or 0)
    decided_count = wins_count + losses_count
    success_rate = round(wins_count * 100 / decided_count, 1) if decided_count else 0.0
    user = profile.user

    return {
        "profile": profile,
        "user": user,
        "avatar": profile.avatar or user.avatar,
        "display_name": profile.display_name or user.get_full_name() or user.username,
        "verified": bool(profile.is_verified),
        "followers_count": int(getattr(profile, "followers_count", 0) or 0),
        "success_rate": success_rate,
        "wins_count": wins_count,
        "losses_count": losses_count,
        "main_sport_category": _main_sport_category(profile),
        "profile_url": reverse("front:expert_profile", args=[user.username]),
        "follow_url": reverse("cabinet:toggle_follow", args=[user.pk]),
        "is_following": bool(getattr(profile, "is_following", False)),
        "vip_sort_at": getattr(profile, "vip_sort_at", None),
    }


def build_vip_cappers_data(limit=DEFAULT_VIP_CAPPERS_LIMIT, *, viewer=None) -> dict:
    """Return the canonical VIP capper source used by every public banner.

    Followers, wins, losses and viewer follow state are SQL annotations on the same
    queryset, while ``user`` is joined with ``select_related``. Rendering the six
    cards therefore does not execute per-capper queries.

    Existing VIP rows do not have a dedicated activation timestamp yet, so
    ``updated_at`` is used as the temporary sort source with ``user.date_joined`` as
    the legacy fallback. Replace ``vip_sort_at`` with ``vip_activated_at`` once every
    VIP purchase/grant flow persists the real activation time.
    """

    safe_limit = _normalize_limit(limit)
    published_filter = Q(
        user__prediction_coupons__published_status=PredictionCoupon.PublishedStatus.PUBLISHED
    )
    wins_filter = published_filter & Q(
        user__prediction_coupons__state_status=PredictionCoupon.StateStatus.WIN
    )
    losses_filter = published_filter & Q(
        user__prediction_coupons__state_status=PredictionCoupon.StateStatus.LOSE
    )

    queryset = (
        AnalystProfile.objects.filter(
            is_vip=True,
            is_public=True,
            user__role=User.Role.ANALYST,
        )
        .select_related("user")
        .annotate(
            followers_count=Count("user__analyst_followers", distinct=True),
            wins_count=Count(
                "user__prediction_coupons",
                filter=wins_filter,
                distinct=True,
            ),
            losses_count=Count(
                "user__prediction_coupons",
                filter=losses_filter,
                distinct=True,
            ),
            # TODO: replace this fallback with AnalystProfile.vip_activated_at when
            # the VIP purchase/grant flow stores an exact activation timestamp.
            vip_sort_at=Coalesce("updated_at", "user__date_joined"),
        )
    )

    if getattr(viewer, "is_authenticated", False):
        queryset = queryset.annotate(
            is_following=Exists(
                AnalystFollow.objects.filter(
                    follower=viewer,
                    analyst_id=OuterRef("user_id"),
                )
            )
        )

    vip_profiles = list(queryset.order_by("-vip_sort_at", "-id")[:safe_limit])
    vip_cappers = [_card_payload(profile) for profile in vip_profiles]

    return {
        "vip_cappers": vip_cappers,
        "vip_main": vip_cappers[0] if vip_cappers else None,
        "vip_list": vip_cappers[1:],
        "vip_ranking_url": reverse("front:cappers_table_group", args=["vip"]),
    }
