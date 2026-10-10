from django.db.models import Count

from cabinet.expert_profile_views import recommended_expert_cards
from cabinet.models import AnalystFollow
from cabinet.vip import annotate_vip_status
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
    followers_by_analyst = {
        row["analyst_id"]: row["followers_count"]
        for row in AnalystFollow.objects.filter(analyst_id__in=analyst_ids)
        .values("analyst_id")
        .annotate(followers_count=Count("id"))
    }
    return recommended_expert_cards(request, profiles, followers_by_analyst)
