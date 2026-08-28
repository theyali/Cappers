from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import ensure_csrf_cookie

from front.capper_stats_service import CapperStatsService

from .models import AnalystProfile, User


@ensure_csrf_cookie
def expert_profile(request, username: str):
    profile = get_object_or_404(
        AnalystProfile.objects.select_related("user"),
        user__username=username,
        user__role=User.Role.ANALYST,
        is_public=True,
    )
    service = CapperStatsService(request.user)
    return render(
        request,
        "cabinet/expert_profile.html",
        service.build_expert_profile_context(profile),
    )
