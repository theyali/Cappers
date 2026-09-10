from math import ceil, floor, log10

from django import template
from django.db.models import Count, Q
from django.urls import reverse

from back.models import Bookmaker, WebsiteSettings
from front.expert_ranking import ranked_expert_profiles
from front.popular_matches import build_popular_matches
from game.models import Match, Prediction, PredictionCoupon

register = template.Library()


SIDEBAR_PROFIT_PERIODS = (
    ("all", "Все время"),
    ("90", "90 дней"),
    ("30", "30 дней"),
    ("7", "7 дней"),
)
SIDEBAR_PROFIT_BAR_SLOTS = 18


def _as_float(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _signed_value(value: float, *, suffix: str = "", digits: int = 1) -> str:
    prefix = "+" if value > 0 else ""
    return f"{prefix}{value:.{digits}f}{suffix}"


def _axis_value(value: float) -> str:
    if abs(value) >= 1000:
        return f"{value / 1000:.1f}k".replace(".0k", "k")
    if abs(value - round(value)) < 0.001:
        return str(int(round(value)))
    return f"{value:.1f}"


def _nice_ceiling(value: float) -> float:
    value = max(float(value), 1.0)
    exponent = floor(log10(value))
    magnitude = 10 ** exponent
    fraction = value / magnitude
    if fraction <= 1:
        nice = 1
    elif fraction <= 2:
        nice = 2
    elif fraction <= 5:
        nice = 5
    else:
        nice = 10
    return float(nice * magnitude)


def _chart_deltas(items) -> list[float]:
    result = []
    previous = 0.0
    for item in items or []:
        current = _as_float((item or {}).get("value"))
        result.append(current - previous)
        previous = current
    return result


def _compress_profit_values(values: list[float]) -> list[float | None]:
    values = [_as_float(value) for value in values]
    if len(values) > SIDEBAR_PROFIT_BAR_SLOTS:
        chunk_size = ceil(len(values) / SIDEBAR_PROFIT_BAR_SLOTS)
        values = [
            sum(values[index : index + chunk_size])
            for index in range(0, len(values), chunk_size)
        ]
    values = values[-SIDEBAR_PROFIT_BAR_SLOTS:]
    return [None] * (SIDEBAR_PROFIT_BAR_SLOTS - len(values)) + values


def _profit_bar_geometry(values: list[float]) -> dict:
    slots = _compress_profit_values(values)
    real_values = [value for value in slots if value is not None]
    positive_peak = max([value for value in real_values if value > 0] or [1.0])
    negative_peak = max([abs(value) for value in real_values if value < 0] or [0.0])

    top_axis = _nice_ceiling(positive_peak * 1.08)
    bottom_axis = _nice_ceiling(max(negative_peak * 1.08, top_axis / 2))

    chart_top = 146.0
    chart_bottom = 258.0
    chart_height = chart_bottom - chart_top
    zero_y = chart_top + (top_axis / (top_axis + bottom_axis)) * chart_height
    positive_height = zero_y - chart_top
    negative_height = chart_bottom - zero_y

    bars = []
    for index, value in enumerate(slots):
        x = 27.0 + index * 17.4
        if value is None:
            bars.append(
                {
                    "x": round(x, 2),
                    "y": round(zero_y, 2),
                    "height": 0,
                    "tone": "empty",
                    "visible": False,
                }
            )
            continue

        if value > 0:
            height = max(2.0, min(positive_height, value / top_axis * positive_height))
            y = zero_y - height
            tone = "positive"
        elif value < 0:
            height = max(2.0, min(negative_height, abs(value) / bottom_axis * negative_height))
            y = zero_y
            tone = "negative"
        else:
            height = 2.0
            y = zero_y - 1.0
            tone = "neutral"

        bars.append(
            {
                "x": round(x, 2),
                "y": round(y, 2),
                "height": round(height, 2),
                "tone": tone,
                "visible": True,
            }
        )

    middle_y = chart_top + (zero_y - chart_top) / 2
    return {
        "bars": bars,
        "grid": [
            round(chart_top, 2),
            round(middle_y, 2),
            round(zero_y, 2),
            round(chart_bottom, 2),
        ],
        "axis": [
            _axis_value(top_axis),
            _axis_value(top_axis / 2),
            "0",
            _axis_value(-bottom_axis),
        ],
    }


def _sidebar_profit_dynamics(context) -> dict:
    chart = context.get("profit_chart") or {}
    profit_periods = context.get("profit_periods") or {}
    average_coefficient = _as_float(context.get("avg_coefficient"))

    monthly_values = [
        _as_float(row.get("total_profit"))
        for row in reversed(context.get("monthly_stats") or [])
    ]
    if len(monthly_values) < 6:
        monthly_values = _chart_deltas(chart.get("90") or [])

    all_profit = _as_float(context.get("total_profit"))
    all_period = {
        "key": "all",
        "label": "Все время",
        "profit": all_profit,
        "profit_display": _signed_value(all_profit),
        "roi": _as_float(context.get("overall_roi")),
        "roi_display": _signed_value(_as_float(context.get("overall_roi")), suffix="%"),
        "count": int(context.get("settled_coupons_count") or 0),
        "avg_coefficient": average_coefficient,
        "avg_coefficient_display": f"{average_coefficient:.2f}",
        **_profit_bar_geometry(monthly_values),
    }

    periods = {"all": all_period}
    for key, label in SIDEBAR_PROFIT_PERIODS[1:]:
        period = profit_periods.get(key) or {}
        profit = _as_float(period.get("profit"))
        roi = _as_float(period.get("roi"))
        periods[key] = {
            "key": key,
            "label": label,
            "profit": profit,
            "profit_display": _signed_value(profit),
            "roi": roi,
            "roi_display": _signed_value(roi, suffix="%"),
            "count": int(period.get("count") or 0),
            "avg_coefficient": average_coefficient,
            "avg_coefficient_display": f"{average_coefficient:.2f}",
            **_profit_bar_geometry(_chart_deltas(chart.get(key) or [])),
        }

    return {
        "periods": periods,
        "options": [
            {"key": key, "label": label}
            for key, label in SIDEBAR_PROFIT_PERIODS
        ],
        "default": all_period,
    }


@register.inclusion_tag("back/_bookmakers_sidebar.html", takes_context=True)
def bookmakers_sidebar(context, force_sidebar_ads=False, show_profit_dynamics=False):
    adv_banners = context.get("adv_banners", [])
    adv_placement = context.get("adv_placement", "content")
    return {
        "bookmakers": Bookmaker.objects.all(),
        "website_settings": WebsiteSettings.load(),
        "promo_banners": context.get("promo_banners", []),
        "adv_banners": adv_banners,
        "adv_placement": adv_placement,
        "show_sidebar_ads": bool(
            adv_banners and (force_sidebar_ads or adv_placement == "sidebar")
        ),
        "show_profit_dynamics": bool(show_profit_dynamics),
        "sidebar_profit_dynamics": (
            _sidebar_profit_dynamics(context) if show_profit_dynamics else None
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
    return {"bookmakers": bookmakers[:3], "is_home_bookmakers": True}


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
