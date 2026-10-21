"""PNG link previews of coupons and capper profiles."""

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.cache import patch_cache_control
from django.views.decorators.http import require_GET

from cabinet.models import AnalystProfile, User

from .data import card_coupons, coupon_card_png, profile_card_png

BROWSER_SECONDS = 60 * 60


def _png_response(png: bytes) -> HttpResponse:
    response = HttpResponse(png, content_type="image/png")
    patch_cache_control(response, public=True, max_age=BROWSER_SECONDS)
    return response


@require_GET
def coupon_image(request, coupon_id: int):
    return _png_response(coupon_card_png(get_object_or_404(card_coupons(), pk=coupon_id)))


@require_GET
def capper_image(request, username: str):
    profile = get_object_or_404(
        AnalystProfile.objects.select_related("user"),
        user__username=username,
        user__role=User.Role.ANALYST,
        is_public=True,
    )
    return _png_response(profile_card_png(profile))
