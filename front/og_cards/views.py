"""PNG link previews, drawn once per content version and kept in the cache."""

from django.core.cache import cache
from django.db.models import Prefetch
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.cache import patch_cache_control
from django.views.decorators.http import require_GET

from cabinet.models import AnalystProfile, User
from game.models import PredictionCoupon

from .cards import coupon_card, profile_card
from .data import coupon_card_data, coupon_card_version, profile_card_data, profile_card_version

CACHE_SECONDS = 60 * 60 * 24 * 7
BROWSER_SECONDS = 60 * 60


def _png(key: str, render) -> HttpResponse:
    png = cache.get(key)
    if png is None:
        png = render()
        cache.set(key, png, CACHE_SECONDS)
    response = HttpResponse(png, content_type="image/png")
    patch_cache_control(response, public=True, max_age=BROWSER_SECONDS)
    return response


@require_GET
def coupon_image(request, coupon_id: int):
    from front.prediction_views import _positions_queryset

    coupon = get_object_or_404(
        PredictionCoupon.objects.filter(published_status=PredictionCoupon.PublishedStatus.PUBLISHED)
        .select_related("author", "author__analyst_profile")
        .prefetch_related(Prefetch("predictions", queryset=_positions_queryset(), to_attr="card_positions")),
        pk=coupon_id,
    )
    key = f"og-card:coupon:{coupon.pk}:{coupon_card_version(coupon)}"
    return _png(key, lambda: coupon_card(coupon_card_data(coupon, coupon.card_positions)))


@require_GET
def capper_image(request, username: str):
    profile = get_object_or_404(
        AnalystProfile.objects.select_related("user"),
        user__username=username,
        user__role=User.Role.ANALYST,
        is_public=True,
    )
    key = f"og-card:capper:{profile.user_id}:{profile_card_version(profile)}"
    return _png(key, lambda: profile_card(profile_card_data(profile)))
