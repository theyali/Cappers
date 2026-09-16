from django import template
from django.db.models import F, IntegerField, Value
from django.db.models.functions import Coalesce

from game.models import PredictionCoupon
from front.models import PredictionFavorite, PredictionLike


register = template.Library()


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


@register.simple_tag
def profile_coupon_reaction_counts(coupon_id):
    row = (
        PredictionCoupon.objects.filter(pk=coupon_id)
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
        "likes": row["likes_count"],
        "favorites": row["favorites_count"],
    }
