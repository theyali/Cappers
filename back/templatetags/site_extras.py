from decimal import Decimal
from types import SimpleNamespace

from django import template
from django.db.models import Count, Prefetch

from back.models import Bookmaker, WebsiteSettings
from game.models import PredictionCoupon, PredictionItem

register = template.Library()


@register.inclusion_tag("back/_bookmakers_sidebar.html", takes_context=True)
def bookmakers_sidebar(context):
    return {
        "bookmakers": Bookmaker.objects.all(),
        "website_settings": WebsiteSettings.load(),
        "adv_banners": context.get("adv_banners", []),
        "adv_placement": context.get("adv_placement", "content"),
    }


@register.inclusion_tag("front/includes/_home_bookmakers.html")
def home_bookmakers():
    bookmakers = list(
        Bookmaker.objects.filter(show_on_home=True).order_by("home_order", "id")
    )
    return {"bookmakers": bookmakers}


@register.inclusion_tag("back/_my_coupons.html")
def my_recent_coupons(user):
    if not getattr(user, "is_authenticated", False):
        return {"my_coupons": []}

    coupons = list(
        PredictionCoupon.objects.filter(
            author=user,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        )
        .annotate(predictions_count=Count("predictions", distinct=True))
        .order_by("-published_at", "-created_at", "-id")[:3]
    )
    for coupon in coupons:
        if coupon.total_stake and coupon.total_stake > 0:
            coupon.sidebar_coefficient = (
                coupon.possible_payout / coupon.total_stake
            ).quantize(Decimal("0.01"))
        else:
            coupon.sidebar_coefficient = Decimal("0.00")
        coupon.sidebar_date = coupon.published_at or coupon.created_at

    return {"my_coupons": coupons}


@register.simple_tag
def latest_prediction_cards(limit=6):
    """Return one sidebar card per prediction, never one card per match item."""
    try:
        limit = max(1, min(int(limit), 20))
    except (TypeError, ValueError):
        limit = 6

    positions = PredictionItem.objects.select_related(
        "match__league__country",
        "match__home_team",
        "match__away_team",
    ).order_by("id")
    coupons = (
        PredictionCoupon.objects.filter(
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        )
        .select_related("author", "author__analyst_profile")
        .prefetch_related(
            Prefetch("predictions", queryset=positions, to_attr="sidebar_positions")
        )
        .annotate(predictions_count=Count("predictions", distinct=True))
        .order_by("-published_at", "-created_at", "-id")[:limit]
    )

    cards = []
    for coupon in coupons:
        items = list(getattr(coupon, "sidebar_positions", []) or [])
        if not items:
            continue

        item = items[0]
        count = coupon.predictions_count or len(items)
        coefficient = Decimal("0")
        if coupon.total_stake:
            coefficient = (coupon.possible_payout / coupon.total_stake).quantize(
                Decimal("0.01")
            )

        market = item.market
        selection = item.selection
        if count > 1:
            market = f"Экспресс · {count} игр"
            selection = f"{item.selection} + ещё {count - 1}"

        cards.append(
            SimpleNamespace(
                id=coupon.id,
                coupon=coupon,
                match=item.match,
                market=market,
                selection=selection,
                coefficient=coefficient,
                state_status=coupon.state_status,
                positions_count=count,
            )
        )

    return cards
