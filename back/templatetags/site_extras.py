from django import template

from back.models import Bookmaker, WebsiteSettings
from front.popular_matches import build_popular_matches

register = template.Library()


@register.inclusion_tag("back/_bookmakers_sidebar.html", takes_context=True)
def bookmakers_sidebar(context):
    return {
        "bookmakers": Bookmaker.objects.all(),
        "website_settings": WebsiteSettings.load(),
        "adv_banners": context.get("adv_banners", []),
        "adv_placement": context.get("adv_placement", "content"),
    }


@register.inclusion_tag("front/includes/_popular_matches.html")
def popular_matches(limit=5):
    return {"popular_matches": build_popular_matches(limit=limit)}


@register.inclusion_tag("front/includes/_home_bookmakers.html")
def home_bookmakers():
    bookmakers = list(
        Bookmaker.objects.filter(show_on_home=True).order_by("home_order", "id")
    )
    return {"bookmakers": bookmakers}
