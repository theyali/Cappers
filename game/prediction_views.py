from django.core.paginator import Paginator
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.views.decorators.csrf import ensure_csrf_cookie

from cabinet.models import AnalystFollow, AnalystProfile
from front.models import PredictionFavorite, PredictionLike
from front.prediction_metrics import annotate_author_roi
from game.models import Match, Prediction, PredictionCoupon


MATCH_PREDICTIONS_PAGE_SIZE = 6


def _initials(name: str) -> str:
    parts = [part for part in name.split() if part]
    return "".join(part[0] for part in parts[:2]).upper() or "К"


def _prediction_distribution(queryset) -> tuple[int, list[dict]]:
    total = queryset.values("coupon_id").distinct().count()
    if not total:
        return 0, []

    rows = (
        queryset.values("market", "selection")
        .annotate(count=Count("coupon_id", distinct=True))
        .order_by()
    )
    distribution = [
        {
            "market": row["market"],
            "selection": row["selection"],
            "count": row["count"],
            "percent": round((row["count"] / total) * 100, 1),
        }
        for row in rows
    ]
    return total, distribution


@ensure_csrf_cookie
def match_predictions(request, slug: str):
    match = get_object_or_404(Match, slug=slug)

    base_queryset = Prediction.objects.filter(
        match=match,
        coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
    )
    total, distribution = _prediction_distribution(base_queryset)

    queryset = (
        base_queryset.select_related(
            "coupon__author",
            "coupon__author__analyst_profile",
            "match__league__country",
            "match__home_team",
            "match__away_team",
        )
        .annotate(likes_count=Count("coupon__likes", distinct=True))
    )
    queryset = annotate_author_roi(queryset).order_by(
        "-coupon__published_at",
        "-coupon__created_at",
        "-created_at",
        "-id",
    )

    paginator = Paginator(queryset, MATCH_PREDICTIONS_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page") or 1)

    prediction_ids = [prediction.coupon_id for prediction in page_obj.object_list]
    liked_ids = set()
    favorite_ids = set()
    following_ids = set()
    if request.user.is_authenticated:
        following_ids = set(
            AnalystFollow.objects.filter(follower=request.user).values_list(
                "analyst_id", flat=True
            )
        )
        if prediction_ids:
            liked_ids = set(
                PredictionLike.objects.filter(
                    user=request.user,
                    prediction_id__in=prediction_ids,
                ).values_list("prediction_id", flat=True)
            )
            favorite_ids = set(
                PredictionFavorite.objects.filter(
                    user=request.user,
                    prediction_id__in=prediction_ids,
                ).values_list("prediction_id", flat=True)
            )

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
        prediction.reaction_id = prediction.coupon_id
        prediction.expert_name = name
        prediction.expert_initials = _initials(name)
        prediction.expert_avatar_url = profile.avatar.url if profile and profile.avatar else ""
        prediction.expert_verified = bool(profile and profile.is_verified)
        prediction.is_liked = prediction.coupon_id in liked_ids
        prediction.is_favorite = prediction.coupon_id in favorite_ids
        prediction.is_own = bool(
            request.user.is_authenticated and author.pk == request.user.pk
        )
        prediction.is_following_author = (
            author.pk in following_ids and not prediction.is_own
        )

    html = render_to_string(
        "game/_match_prediction_cards.html",
        {"predictions": page_obj.object_list},
        request=request,
    )

    return JsonResponse(
        {
            "ok": True,
            "html": html,
            "total": total,
            "distribution": distribution,
            "page": page_obj.number,
            "has_next": page_obj.has_next(),
            "next_page": page_obj.next_page_number() if page_obj.has_next() else None,
        }
    )
