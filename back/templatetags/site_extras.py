from django import template
from django.db.models import Count

from back.models import Bookmaker, WebsiteSettings
from game.models import PredictionCoupon

register = template.Library()


@register.inclusion_tag("back/_bookmakers_sidebar.html")
def bookmakers_sidebar():
    return {
        "bookmakers": Bookmaker.objects.all(),
        "website_settings": WebsiteSettings.load(),
    }


@register.inclusion_tag("back/_my_coupons.html")
def my_recent_coupons(user):
    if not getattr(user, "is_authenticated", False):
        return {"my_coupons": []}

    coupons = (
        PredictionCoupon.objects.filter(author=user)
        .annotate(predictions_count=Count("predictions", distinct=True))
        .order_by("-created_at", "-id")[:3]
    )
    return {"my_coupons": coupons}
