from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string

from cabinet.models import AnalystProfile
from game.models import Match, Prediction, PredictionCoupon


MATCH_PREDICTIONS_PAGE_SIZE = 6


def _initials(name: str) -> str:
    parts = [part for part in name.split() if part]
    return "".join(part[0] for part in parts[:2]).upper() or "К"


def match_predictions(request, slug: str):
    match = get_object_or_404(Match, slug=slug)

    queryset = (
        Prediction.objects.filter(
            match=match,
            coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        )
        .select_related(
            "coupon__author",
            "coupon__author__analyst_profile",
            "match__league",
            "match__home_team",
            "match__away_team",
        )
        .order_by("-coupon__published_at", "-coupon__created_at", "-created_at", "-id")
    )

    paginator = Paginator(queryset, MATCH_PREDICTIONS_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page") or 1)

    for prediction in page_obj.object_list:
        author = prediction.coupon.author
        try:
            profile = author.analyst_profile
        except AnalystProfile.DoesNotExist:
            profile = None

        name = (
            profile.display_name
            if profile and profile.display_name
            else author.get_full_name() or author.username
        )
        prediction.expert_name = name
        prediction.expert_initials = _initials(name)
        prediction.expert_avatar_url = profile.avatar.url if profile and profile.avatar else ""
        prediction.expert_verified = bool(profile and profile.is_verified)

    html = render_to_string(
        "game/_match_prediction_cards.html",
        {"predictions": page_obj.object_list},
        request=request,
    )

    return JsonResponse(
        {
            "ok": True,
            "html": html,
            "total": paginator.count,
            "page": page_obj.number,
            "has_next": page_obj.has_next(),
            "next_page": page_obj.next_page_number() if page_obj.has_next() else None,
        }
    )
