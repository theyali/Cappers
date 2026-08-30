from django import template
from django.db.models import Count, Q
from django.urls import reverse

from back.models import Bookmaker, WebsiteSettings
from front.expert_ranking import ranked_expert_profiles
from front.popular_matches import build_popular_matches
from game.models import Match, Prediction, PredictionCoupon

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


@register.inclusion_tag("game/includes/_latest_match_predictions.html")
def latest_match_predictions(limit=5):
    try:
        safe_limit = max(1, min(int(limit), 12))
    except (TypeError, ValueError):
        safe_limit = 5

    coupons = (
        PredictionCoupon.objects.filter(
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            predictions__match__isnull=False,
        )
        .select_related(
            "author",
            "author__analyst_profile",
        )
        .prefetch_related(
            "predictions__match__home_team",
            "predictions__match__away_team",
            "predictions__match__league",
            "predictions__match__sport",
        )
        .order_by("-published_at", "-created_at")
        .distinct()[: safe_limit * 2]
    )

    seen_matches: set[int] = set()
    items = []
    for coupon in coupons:
        prediction = next(
            (p for p in coupon.predictions.all() if p.match_id),
            None,
        )
        if prediction is None:
            continue
        match = prediction.match
        if match.pk in seen_matches:
            continue
        seen_matches.add(match.pk)

        author = coupon.author
        profile = getattr(author, "analyst_profile", None)
        expert_name = (
            profile.display_name
            if profile and profile.display_name
            else author.get_full_name() or author.username
        )
        items.append(
            {
                "url": reverse("front:prediction_detail", args=[coupon.pk]),
                "coupon_id": coupon.pk,
                "expert_name": expert_name,
                "expert_verified": bool(profile and profile.is_verified),
                "published_at": coupon.published_at or coupon.created_at,
                "market": prediction.market,
                "selection": prediction.selection,
                "coefficient": prediction.coefficient,
                "home_name": match.home_team_name or "",
                "away_name": match.away_team_name or "",
                "home_logo": (
                    match.home_team.logo
                    if match.home_team and match.home_team.logo
                    else ""
                ),
                "away_logo": (
                    match.away_team.logo
                    if match.away_team and match.away_team.logo
                    else ""
                ),
                "league_name": match.league_name or "",
                "sport_name": (
                    match.sport.name_ru or match.sport.name if match.sport else ""
                ),
                "starts_at": match.starts_at,
            }
        )
        if len(items) >= safe_limit:
            break

    return {"latest_match_predictions": items}


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


@register.inclusion_tag("front/includes/_hot_matches_sidebar.html")
def hot_matches_sidebar(limit=6):
    try:
        safe_limit = max(1, min(int(limit), 12))
    except (TypeError, ValueError):
        safe_limit = 6

    matches = (
        Match.objects.filter(
            sync_scope__in=(Match.SyncScope.PREMATCH, Match.SyncScope.LIVE),
        )
        .annotate(
            prediction_count=Count(
                "predictions",
                filter=Q(
                    predictions__coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
                ),
            )
        )
        .filter(prediction_count__gt=0)
        .select_related("sport", "league")
        .order_by("-prediction_count", "-starts_at")[:safe_limit]
    )

    return {"hot_matches": matches}
