from django import template
from django.db.models import Count

from game.models import PredictionCoupon
from front.models import PredictionFavorite, PredictionLike


register = template.Library()


@register.inclusion_tag("front/includes/_coupon_reactions.html", takes_context=True)
def coupon_reactions(context, coupon: PredictionCoupon):
    request = context.get("request")
    user = getattr(request, "user", None)
    is_authenticated = bool(user and user.is_authenticated)
    is_own = bool(is_authenticated and coupon.author_id == user.id)

    is_liked = False
    is_favorite = False
    if is_authenticated and not is_own:
        is_liked = PredictionLike.objects.filter(
            prediction_id=coupon.id,
            user_id=user.id,
        ).exists()
        is_favorite = PredictionFavorite.objects.filter(
            prediction_id=coupon.id,
            user_id=user.id,
        ).exists()

    return {
        "request": request,
        "coupon": coupon,
        "is_authenticated": is_authenticated,
        "is_own": is_own,
        "is_liked": is_liked,
        "is_favorite": is_favorite,
        "likes_count": coupon.likes.count(),
        "favorites_count": coupon.favorites.count(),
    }


@register.simple_tag
def profile_coupon_reaction_counts(coupon_id):
    row = (
        PredictionCoupon.objects.filter(pk=coupon_id)
        .annotate(
            likes_count=Count("likes", distinct=True),
            favorites_count=Count("favorites", distinct=True),
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
