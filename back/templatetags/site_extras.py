from django import template

from back.models import Bookmaker, WebsiteSettings
from front.expert_ranking import ranked_expert_profiles
from front.popular_matches import build_popular_matches

register = template.Library()


@register.inclusion_tag("back/_bookmakers_sidebar.html", takes_context=True)
def bookmakers_sidebar(context, force_sidebar_ads=False):
    adv_banners = context.get("adv_banners", [])
    adv_placement = context.get("adv_placement", "content")
    return {
        "bookmakers": Bookmaker.objects.all(),
        "website_settings": WebsiteSettings.load(),
        "adv_banners": adv_banners,
        "adv_placement": adv_placement,
        "show_sidebar_ads": bool(
            adv_banners and (force_sidebar_ads or adv_placement == "sidebar")
        ),
    }


@register.inclusion_tag("front/includes/_popular_matches.html")
def popular_matches(limit=5):
    return {"popular_matches": build_popular_matches(limit=limit)}


@register.inclusion_tag("front/includes/_vip_experts_sidebar.html")
def vip_experts_sidebar(limit=5):
    try:
        safe_limit = max(1, min(int(limit), 12))
    except (TypeError, ValueError):
        safe_limit = 5

    vip_experts = []
    for profile in ranked_expert_profiles():
        if not profile.is_vip:
            continue
        vip_experts.append(profile)
        if len(vip_experts) >= safe_limit:
            break

    return {"vip_experts": vip_experts}


@register.inclusion_tag("front/includes/_home_bookmakers.html")
def home_bookmakers():
    bookmakers = list(
        Bookmaker.objects.filter(show_on_home=True).order_by("home_order", "id")
    )
    return {"bookmakers": bookmakers}
