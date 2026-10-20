"""Shared server-side filtering and paging for cabinet and public coupon feeds."""
from types import SimpleNamespace
from urllib.parse import urlencode

from django.db.models import Min, OuterRef, Subquery
from django.template.loader import render_to_string
from django.urls import reverse

from cabinet.paid_predictions import get_active_paid_plans, accessible_paid_coupon_ids

from game.models import PredictionCoupon

PAGE_SIZE = 12
SORT_KEYS = {"date", "stake", "payout", "likes", "favorites"}
STATES = {"all", "win", "lose", "pending", "refund"}


def build_coupon_feed_context(user, params, *, public=False, offset=None, viewer=None, purchased=False, refunded=False):
    from cabinet.views import _profile_coupons_queryset, _sort_profile_coupons, _expert_mobile_coupon_cards

    sort = params.get("coupon_sort", params.get("sort", "date"))
    direction = params.get("coupon_direction", params.get("direction", "desc"))
    state = params.get("coupon_filter", params.get("state", "all"))
    sort = sort if sort in (SORT_KEYS | {"price"} if purchased else SORT_KEYS) else "date"
    direction = direction if direction in {"asc", "desc"} else "desc"
    state = state if state in STATES else "all"
    if offset is None:
        try:
            offset = max(0, int(params.get("offset", 0)))
        except (TypeError, ValueError):
            offset = 0
    purchase_rows = None
    if purchased:
        from cabinet.paid_predictions import paid_coupon_purchases
        if refunded:
            from cabinet.models import PaidPredictionPurchase
            purchase_rows = PaidPredictionPurchase.objects.filter(buyer=user, status=PaidPredictionPurchase.Status.REFUNDED)
        else:
            purchase_rows = paid_coupon_purchases(user)
    queryset = _profile_coupons_queryset(user, purchased_coupon_ids=purchase_rows.values("coupon_id") if purchased else None)
    if purchased:
        purchases = purchase_rows.filter(coupon_id=OuterRef("pk")).order_by("-paid_at", "-pk")
        queryset = queryset.select_related("author").annotate(
            purchase_price=Subquery(purchases.values("price")[:1]),
            purchase_paid_at=Subquery(purchases.values("paid_at")[:1]),
            purchase_refunded_at=Subquery(purchases.values("refunded_at")[:1]),
        )
        if refunded:
            queryset = queryset.prefetch_related(None)
    if public:
        queryset = queryset.filter(
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        )
    available = queryset.exists()
    if state != "all":
        queryset = queryset.filter(state_status=state)
    total = queryset.count()
    if purchased and sort in {"date", "price"}:
        prefix = "" if direction == "asc" else "-"
        field = ("purchase_refunded_at" if refunded else "purchase_paid_at") if sort == "date" else "purchase_price"
        queryset = queryset.order_by(f"{prefix}{field}", f"{prefix}pk")
    else:
        queryset = _sort_profile_coupons(queryset, sort, direction)
    rows = list(queryset[offset:offset + PAGE_SIZE + 1])
    visible = rows[:PAGE_SIZE]
    accessible_ids = accessible_paid_coupon_ids(viewer if public else user, visible)
    accessible = [] if refunded else [row for row in visible if row.audience != PredictionCoupon.Audience.PAID or row.pk in accessible_ids]
    by_id = {card["id"]: card for card in _expert_mobile_coupon_cards(accessible)}
    locked_context = None
    cards = []
    from cabinet.paid_prediction_purchases import single_coupon_offer
    for row in visible:
        if not purchased:
            row.author = user
        is_paid = row.audience == PredictionCoupon.Audience.PAID
        if refunded:
            cards.append({
                "id": row.pk, "is_refunded": True, "purchase_author": row.author.username,
                "purchase_price": row.purchase_price, "purchase_paid_at": row.purchase_paid_at,
                "purchase_refunded_at": row.purchase_refunded_at,
            })
            continue
        if is_paid and row.pk not in accessible_ids:
            if locked_context is None:
                locked_context = build_locked_coupon_author_context(user)
            is_completed = row.state_status != PredictionCoupon.StateStatus.PENDING or row.settled_at is not None
            # No match, pick, odds, stake or payout is put into a locked card.
            cards.append({
                "id": row.pk, "is_paid": True, "is_paid_locked": True,
                "is_completed": is_completed,
                "status_label": "Завершён" if is_completed else "Активный",
                "locked_prediction": SimpleNamespace(
                    **locked_context,
                    **single_coupon_offer(row),
                    coupon=SimpleNamespace(id=row.pk, author_id=user.pk, author=locked_context["author"]),
                    created_at=row.created_at,
                    unique_opens_count=row.unique_opens_count,
                    is_paid_purchase_closed=row.state_status != PredictionCoupon.StateStatus.PENDING,
                ),
            })
        elif row.pk in by_id:
            card = {**by_id[row.pk], "is_paid": is_paid, "is_paid_locked": False}
            if purchased:
                card.update(purchase_price=row.purchase_price, purchase_paid_at=row.purchase_paid_at, purchase_author=row.author.username)
            cards.append(card)
    return {
        "coupon_feed_purchased": purchased,
        "coupon_feed_purchase_status": "refunded" if refunded else "paid",
        "coupon_feed_title": "Возвраты" if refunded else "Купленные купоны" if purchased else "Все прогнозы",
        "coupon_feed_show_zero_opens": not public,
        "coupon_opens_started_at": queryset.aggregate(start=Min("metrics__unique_opens_started_at"))["start"] if not public else None,
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
            "coupon_feed_show_zero_opens": context["coupon_feed_show_zero_opens"],
        }, request=request),
        "desktop_html": render_to_string("cabinet/includes/_profile_mobile_coupon_items.html", {
            "mobile_coupons": context["coupon_feed_items"],
            "coupon_feed_show_zero_opens": context["coupon_feed_show_zero_opens"], "desktop": True,
        }, request=request),
        "has_more": context["coupon_feed_has_more"],
        "next_offset": context["coupon_feed_next_offset"],
        "total": context["coupon_feed_total"],
        "title": context["coupon_feed_title"],
    }


