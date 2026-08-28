from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import ensure_csrf_cookie

from front.capper_stats_service import CapperStatsService
from front.prediction_views import _decorate_predictions, _published_queryset

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
    context = service.build_expert_profile_context(profile)

    latest_coupons = (
        _published_queryset()
        .filter(author=profile.user)
        .order_by("-published_at", "-created_at", "-id")[:12]
    )
    context["latest_predictions"] = _decorate_predictions(request, latest_coupons)

    return render(
        request,
        "cabinet/expert_profile.html",
        context,
    )
