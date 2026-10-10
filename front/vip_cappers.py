from django.db.models import Count, Exists, OuterRef, Q
from django.urls import reverse

from cabinet.models import AnalystFollow, AnalystProfile, User
from cabinet.vip import annotate_vip_status
from game.models import PredictionCoupon


DEFAULT_VIP_CAPPERS_LIMIT = 6
MAX_VIP_CAPPERS_LIMIT = 12


def _normalize_limit(limit) -> int:
    try:
        return max(1, min(int(limit), MAX_VIP_CAPPERS_LIMIT))
    except (TypeError, ValueError):
        return DEFAULT_VIP_CAPPERS_LIMIT


def _attach_counts(profiles: list[AnalystProfile]) -> None:
    """Followers and results of the few cards shown, counted per table so the rows don't multiply."""
    user_ids = [profile.user_id for profile in profiles]
    followers = dict(
        AnalystFollow.objects.filter(analyst_id__in=user_ids)
        .order_by()
        .values("analyst_id")
        .annotate(total=Count("id"))
        .values_list("analyst_id", "total")
    )
    results = {
        row["author_id"]: row
        for row in PredictionCoupon.objects.filter(
            author_id__in=user_ids,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        )
        .order_by()
        .values("author_id")
        .annotate(
            wins=Count("id", filter=Q(state_status=PredictionCoupon.StateStatus.WIN)),
            losses=Count("id", filter=Q(state_status=PredictionCoupon.StateStatus.LOSE)),
        )
    }
    for profile in profiles:
        profile.followers_count = followers.get(profile.user_id, 0)
        profile.wins_count = results.get(profile.user_id, {}).get("wins", 0)
        profile.losses_count = results.get(profile.user_id, {}).get("losses", 0)


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
        "avatar": user.avatar,
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
        "is_vip": bool(getattr(profile, "is_vip_active", False)),
        "vip_ends_at": getattr(profile, "vip_ends_at", None),
        "vip_sort_at": getattr(profile, "vip_sort_at", None),
    }


def build_vip_cappers_data(limit=DEFAULT_VIP_CAPPERS_LIMIT, *, viewer=None) -> dict:
    """Return the canonical VIP capper source used by every public banner.

    VIP state and viewer follow state are SQL annotations on the profile queryset;
    followers, wins and losses come from two grouped queries for the cards shown.
    Rendering the six cards therefore does not execute per-capper queries.

    The top card is the latest active VIP activation.
    """

    safe_limit = _normalize_limit(limit)
    queryset = AnalystProfile.objects.filter(
        is_public=True,
        user__role=User.Role.ANALYST,
    ).select_related("user")
    queryset = annotate_vip_status(
        queryset,
        user_outer_ref="user_id",
        activated_annotation_name="vip_sort_at",
    ).filter(is_vip_active=True)

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
    _attach_counts(vip_profiles)
    vip_cappers = [_card_payload(profile) for profile in vip_profiles]

    return {
        "vip_cappers": vip_cappers,
        "vip_main": vip_cappers[0] if vip_cappers else None,
        "vip_list": vip_cappers[1:],
        "vip_ranking_url": reverse("front:cappers_table_group", args=["vip"]),
    }
