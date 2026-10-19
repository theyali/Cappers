"""Shared server-side filtering and paging for cabinet and public coupon feeds."""
from types import SimpleNamespace
from urllib.parse import urlencode

from django.template.loader import render_to_string
from django.urls import reverse

from cabinet.paid_predictions import get_active_paid_plans, user_can_view_paid_predictions

from game.models import PredictionCoupon

PAGE_SIZE = 12
SORT_KEYS = {"date", "stake", "payout", "likes", "favorites"}
STATES = {"all", "win", "lose", "pending", "refund"}


def build_coupon_feed_context(user, params, *, public=False, offset=None, viewer=None):
    from cabinet.views import _profile_coupons_queryset, _sort_profile_coupons, _expert_mobile_coupon_cards

    sort = params.get("coupon_sort", params.get("sort", "date"))
    direction = params.get("coupon_direction", params.get("direction", "desc"))
    state = params.get("coupon_filter", params.get("state", "all"))
    sort = sort if sort in SORT_KEYS else "date"
    direction = direction if direction in {"asc", "desc"} else "desc"
    state = state if state in STATES else "all"
    if offset is None:
        try:
            offset = max(0, int(params.get("offset", 0)))
        except (TypeError, ValueError):
            offset = 0
    queryset = _profile_coupons_queryset(user)
    if public:
        queryset = queryset.filter(
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        )
    available = queryset.exists()
    if state != "all":
        queryset = queryset.filter(state_status=state)
    total = queryset.count()
    rows = list(_sort_profile_coupons(queryset, sort, direction)[offset:offset + PAGE_SIZE + 1])
    visible = rows[:PAGE_SIZE]
    can_view_paid = user_can_view_paid_predictions(viewer if public else user, user)
    accessible = [row for row in visible if row.audience != PredictionCoupon.Audience.PAID or can_view_paid]
    by_id = {card["id"]: card for card in _expert_mobile_coupon_cards(accessible)}
    locked_context = None
    cards = []
    for row in visible:
        is_paid = row.audience == PredictionCoupon.Audience.PAID
        if is_paid and not can_view_paid:
            if locked_context is None:
                locked_context = build_locked_coupon_author_context(user)
            # No match, pick, odds, stake or payout is put into a locked card.
            cards.append({
                "id": row.pk, "is_paid": True, "is_paid_locked": True,
                "locked_prediction": SimpleNamespace(
                    **locked_context,
                    coupon=SimpleNamespace(id=row.pk, author_id=user.pk, author=locked_context["author"]),
                    created_at=row.created_at,
                    is_paid_purchase_closed=row.state_status != PredictionCoupon.StateStatus.PENDING,
                ),
            })
        elif row.pk in by_id:
            cards.append({**by_id[row.pk], "is_paid": is_paid, "is_paid_locked": False})
    return {
        "coupon_feed_items": cards,
        "coupon_feed_available": available,
        "coupon_feed_total": total,
        "coupon_feed_has_more": len(rows) > PAGE_SIZE,
        "coupon_feed_next_offset": offset + min(len(rows), PAGE_SIZE),
        "coupon_feed_sort": sort,
        "coupon_feed_direction": direction,
        "coupon_feed_filter": state,
    }


def build_locked_coupon_author_context(user):
    from cabinet.views import _initials

    profile = user.analyst_profile
    name = profile.display_name or user.get_full_name() or user.username
    plan = get_active_paid_plans(user).first()
    next_url = reverse("front:expert_profile", kwargs={"username": user.username}) + "#predictions"
    checkout = reverse("cabinet:paid_predictions_subscribe", kwargs={"user_id": user.pk})
    return {
        "author": SimpleNamespace(username=user.username, is_vip=user.is_vip),
        "expert_name": name, "expert_initials": _initials(name),
        "expert_avatar_url": user.avatar.url if user.avatar else "",
        "expert_verified": profile.is_verified, "expert_trust_index": profile.trust_index,
        "paid_access_price": plan.price if plan else profile.paid_predictions_price,
        "paid_access_period": plan.period_label if plan else "30 дней",
        "paid_checkout_url": f"{checkout}?{urlencode({'next': next_url})}",
    }


def build_coupon_feed_payload(request, context):
    return {
        "ok": True,
        "html": render_to_string("cabinet/includes/_profile_mobile_coupon_items.html", {
            "mobile_coupons": context["coupon_feed_items"],
        }, request=request),
        "desktop_html": render_to_string("cabinet/includes/_profile_mobile_coupon_items.html", {
            "mobile_coupons": context["coupon_feed_items"], "desktop": True,
        }, request=request),
        "has_more": context["coupon_feed_has_more"],
        "next_offset": context["coupon_feed_next_offset"],
        "total": context["coupon_feed_total"],
    }


