from django.db.models import Count, Sum
from django.urls import reverse

from cabinet.expert_profile_views import _initials, _prediction_word
from cabinet.models import AnalystFollow, CapperMonthlyStat
from cabinet.vip import annotate_vip_status, attach_vip_status_to_user
from front.expert_ranking import recommended_experts_for_user as matching_expert_profiles


def personalized_recommended_experts(request, *, limit: int = 8) -> list[dict]:
    profiles = matching_expert_profiles(request.user, limit=limit)
    if not profiles:
        return []

    profile_ids = [profile.pk for profile in profiles]
    vip_profiles = annotate_vip_status(
        type(profiles[0]).objects.filter(pk__in=profile_ids).select_related("user"),
        user_outer_ref="user_id",
        activated_annotation_name="active_vip_activated_at",
    )
    profiles_by_id = {profile.pk: profile for profile in vip_profiles}
    profiles = [profiles_by_id.get(profile.pk, profile) for profile in profiles]

    analyst_ids = [profile.user_id for profile in profiles]
    stats_by_analyst = {
        row["analyst_id"]: row
        for row in CapperMonthlyStat.objects.filter(analyst_id__in=analyst_ids)
        .values("analyst_id")
        .annotate(
            predictions_count=Sum("bets_count"),
            wins_count=Sum("wins_count"),
            losses_count=Sum("losses_count"),
            refunds_count=Sum("refunds_count"),
        )
    }
    followers_by_analyst = {
        row["analyst_id"]: row["followers_count"]
        for row in AnalystFollow.objects.filter(analyst_id__in=analyst_ids)
        .values("analyst_id")
        .annotate(followers_count=Count("id"))
    }
    following_ids: set[int] = set()
    if request.user.is_authenticated:
        following_ids = set(
            AnalystFollow.objects.filter(
                follower=request.user,
                analyst_id__in=analyst_ids,
            ).values_list("analyst_id", flat=True)
        )

    result = []
    for profile in profiles:
        user = profile.user
        attach_vip_status_to_user(user, profile)
        name = profile.display_name or user.get_full_name() or user.username
        avatar_url = ""
        if user.avatar:
            avatar_url = user.avatar.url
        stats = stats_by_analyst.get(profile.user_id, {})
        predictions_count = int(stats.get("predictions_count") or 0)
        result.append(
            {
                "id": profile.user_id,
                "username": user.username,
                "name": name,
                "initials": _initials(name),
                "avatar_url": avatar_url,
                "is_vip": bool(user.is_vip),
                "trust_index": profile.trust_index,
                "profile_url": reverse(
                    "front:expert_profile",
                    kwargs={"username": user.username},
                ),
                "followers_count": int(followers_by_analyst.get(profile.user_id, 0)),
                "predictions_count": predictions_count,
                "predictions_label": _prediction_word(predictions_count),
                "wins_count": int(stats.get("wins_count") or 0),
                "losses_count": int(stats.get("losses_count") or 0),
                "refunds_count": int(stats.get("refunds_count") or 0),
                "is_following": profile.user_id in following_ids,
            }
        )
    return result
