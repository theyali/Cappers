from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from .models import AnalystProfile, User
from .services.profile_coupon_feed import build_coupon_feed_context, build_coupon_feed_payload


@require_GET
def expert_coupons(request, username):
    profile = get_object_or_404(
        AnalystProfile.objects.select_related("user"),
        user__username=username, user__role=User.Role.ANALYST, is_public=True,
    )
    return JsonResponse(build_coupon_feed_payload(request, build_coupon_feed_context(
        profile.user, request.GET, public=True, viewer=request.user,
    )))
