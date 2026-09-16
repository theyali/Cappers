from django import template
from django.db.models import F, IntegerField, Value
from django.db.models.functions import Coalesce

from game.models import PredictionCoupon
from front.models import PredictionFavorite, PredictionLike


register = template.Library()
PROFILE_REACTION_CACHE_ATTR = "_profile_coupon_reaction_metrics"


def _reaction_metric_counts(coupon: PredictionCoupon) -> tuple[int, int]:
    likes_count = getattr(coupon, "likes_count", None)
    favorites_count = getattr(coupon, "favorites_count", None)
    if likes_count is not None and favorites_count is not None:
        return int(likes_count or 0), int(favorites_count or 0)

    metrics = getattr(coupon, "metrics", None)
    if metrics is not None:
        return int(metrics.likes_count or 0), int(metrics.favorites_count or 0)

    row = (
        PredictionCoupon.objects.filter(pk=coupon.pk)
        .annotate(
            metric_likes_count=Coalesce(
                F("metrics__likes_count"),
                Value(0),
                output_field=IntegerField(),
            ),
            metric_favorites_count=Coalesce(
                F("metrics__favorites_count"),
                Value(0),
                output_field=IntegerField(),
            ),
        )
        .values("metric_likes_count", "metric_favorites_count")
        .first()
    )
    if not row:
        return 0, 0
    return int(row["metric_likes_count"] or 0), int(row["metric_favorites_count"] or 0)


def _profile_reaction_metrics(request) -> dict[int, dict[str, int]]:
    cached = getattr(request, PROFILE_REACTION_CACHE_ATTR, None)
    if cached is not None:
        return cached

    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        cached = {}
    else:
        rows = (
            PredictionCoupon.objects.filter(author_id=user.pk)
            .annotate(
                likes_count=Coalesce(
                    F("metrics__likes_count"),
                    Value(0),
                    output_field=IntegerField(),
                ),
                favorites_count=Coalesce(
                    F("metrics__favorites_count"),
                    Value(0),
                    output_field=IntegerField(),
                ),
            )
            .values("id", "likes_count", "favorites_count")
        )
        cached = {
            int(row["id"]): {
                "likes": int(row["likes_count"] or 0),
                "favorites": int(row["favorites_count"] or 0),
            }
            for row in rows
        }

    setattr(request, PROFILE_REACTION_CACHE_ATTR, cached)
    return cached


@register.inclusion_tag("front/includes/_coupon_reactions.html", takes_context=True)
def coupon_reactions(context, coupon: PredictionCoupon):
    request = context.get("request")
    user = getattr(request, "user", None)
    is_authenticated = bool(user and user.is_authenticated)
    is_own = bool(is_authenticated and coupon.author_id == user.id)

    is_liked = bool(getattr(coupon, "is_liked", False))
    is_favorite = bool(getattr(coupon, "is_favorite", False))
    if is_authenticated and not is_own:
        if not hasattr(coupon, "is_liked"):
            is_liked = PredictionLike.objects.filter(
                prediction_id=coupon.id,
                user_id=user.id,
            ).exists()
        if not hasattr(coupon, "is_favorite"):
            is_favorite = PredictionFavorite.objects.filter(
                prediction_id=coupon.id,
                user_id=user.id,
            ).exists()

    likes_count, favorites_count = _reaction_metric_counts(coupon)
    return {
        "request": request,
        "coupon": coupon,
        "is_authenticated": is_authenticated,
        "is_own": is_own,
        "is_liked": is_liked,
        "is_favorite": is_favorite,
        "likes_count": likes_count,
        "favorites_count": favorites_count,
    }


@register.simple_tag(takes_context=True)
def profile_coupon_reaction_counts(context, coupon_id):
    try:
        normalized_id = int(coupon_id)
    except (TypeError, ValueError):
        return {"likes": 0, "favorites": 0}

    request = context.get("request")
    if request is not None:
        cached = _profile_reaction_metrics(request)
        if normalized_id in cached:
            return cached[normalized_id]

    row = (
        PredictionCoupon.objects.filter(pk=normalized_id)
        .annotate(
            likes_count=Coalesce(
                F("metrics__likes_count"),
                Value(0),
                output_field=IntegerField(),
            ),
            favorites_count=Coalesce(
                F("metrics__favorites_count"),
                Value(0),
                output_field=IntegerField(),
            ),
        )
        .values("likes_count", "favorites_count")
        .first()
    )
    if not row:
        return {"likes": 0, "favorites": 0}
    return {
        "likes": int(row["likes_count"] or 0),
        "favorites": int(row["favorites_count"] or 0),
    }
