from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie

from cabinet.models import AnalystFollow, AnalystPaidSubscription
from cabinet.paid_predictions import active_paid_subscription_analyst_ids
from game.models import PredictionCoupon

from .prediction_views import (
    PREDICTIONS_PAGE_SIZE,
    _decorate_predictions,
    _published_queryset,
    _status_tabs,
    prediction_filter_collapsed,
)
from .views import PREDICTION_STATUS_FILTERS


FEED_SORT_OPTIONS = (
    ("new", "Новые"),
    ("popular", "Популярные"),
)
PAID_FEED_LIMIT = 12


def _feed_url(request, params) -> str:
    query = params.urlencode()
    return f"{request.path}?{query}" if query else request.path


def _apply_feed_filters(queryset, *, selected_capper, only_live, only_today):
    if selected_capper:
        queryset = queryset.filter(author__username=selected_capper)
    if only_live:
        queryset = queryset.filter(predictions__match__sync_scope="live")
    if only_today:
        queryset = queryset.filter(predictions__match__starts_at__date=timezone.localdate())
    return queryset.distinct()


def _feed_counts(queryset) -> dict:
    return queryset.aggregate(
        total=Count("id", distinct=True),
        pending=Count(
            "id",
            filter=Q(state_status=PredictionCoupon.StateStatus.PENDING),
            distinct=True,
        ),
        win=Count(
            "id",
            filter=Q(state_status=PredictionCoupon.StateStatus.WIN),
            distinct=True,
        ),
        lose=Count(
            "id",
            filter=Q(state_status=PredictionCoupon.StateStatus.LOSE),
            distinct=True,
        ),
        refund=Count(
            "id",
            filter=Q(state_status=PredictionCoupon.StateStatus.REFUND),
            distinct=True,
        ),
    )


@login_required
@ensure_csrf_cookie
def following_feed(request):
    active_status = request.GET.get("status", "all")
    valid_statuses = {key for key, _ in PREDICTION_STATUS_FILTERS}
    if active_status not in valid_statuses:
        active_status = "all"

    active_sort = request.GET.get("sort", "new")
    valid_sorts = {key for key, _ in FEED_SORT_OPTIONS}
    if active_sort not in valid_sorts:
        active_sort = "new"

    following = list(
        AnalystFollow.objects.filter(follower=request.user)
        .select_related("analyst", "analyst__analyst_profile")
        .order_by("-created_at")
    )
    following_ids = {follow.analyst_id for follow in following}
    followed_usernames = {follow.analyst.username for follow in following}
    paid_subscriptions = list(
        AnalystPaidSubscription.objects.filter(
            subscriber=request.user,
            expires_at__gt=timezone.now(),
        )
        .select_related("analyst", "analyst__analyst_profile")
        .order_by("-expires_at", "-id")
    )
    paid_analyst_ids = active_paid_subscription_analyst_ids(request.user)
    paid_usernames = {subscription.analyst.username for subscription in paid_subscriptions}

    selected_capper = request.GET.get("capper", "").strip()
    if selected_capper and selected_capper not in followed_usernames | paid_usernames:
        selected_capper = ""

    only_live = request.GET.get("live") == "1"
    only_today = request.GET.get("today") == "1"

    queryset = _apply_feed_filters(
        _published_queryset().filter(author_id__in=following_ids),
        selected_capper=selected_capper,
        only_live=only_live,
        only_today=only_today,
    )
    paid_queryset = _apply_feed_filters(
        _published_queryset(include_paid=True).filter(
            is_paid=True,
            author_id__in=paid_analyst_ids,
        ),
        selected_capper=selected_capper,
        only_live=only_live,
        only_today=only_today,
    )

    count_keys = ("total", "pending", "win", "lose", "refund")
    free_counts = _feed_counts(queryset)
    paid_counts = _feed_counts(paid_queryset)
    counts = {
        key: (free_counts.get(key) or 0) + (paid_counts.get(key) or 0)
        for key in count_keys
    }

    if active_status == "pending":
        queryset = queryset.filter(state_status=PredictionCoupon.StateStatus.PENDING)
    elif active_status != "all":
        queryset = queryset.filter(state_status=active_status)
    if active_status == "pending":
        paid_queryset = paid_queryset.filter(state_status=PredictionCoupon.StateStatus.PENDING)
    elif active_status != "all":
        paid_queryset = paid_queryset.filter(state_status=active_status)

    if active_sort == "popular":
        queryset = queryset.order_by(
            "-likes_count",
            "-favorites_count",
            "-published_at",
            "-created_at",
        )
        paid_queryset = paid_queryset.order_by(
            "-likes_count",
            "-favorites_count",
            "-published_at",
            "-created_at",
        )
    else:
        queryset = queryset.order_by("-published_at", "-created_at")
        paid_queryset = paid_queryset.order_by("-published_at", "-created_at")

    paginator = Paginator(queryset, PREDICTIONS_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))
    page_obj.object_list = _decorate_predictions(
        request,
        page_obj.object_list,
        following_ids=following_ids,
    )
    paid_predictions_count = paid_queryset.count()
    paid_predictions = _decorate_predictions(
        request,
        paid_queryset[:PAID_FEED_LIMIT],
        following_ids=following_ids,
    )
    paid_upgrade_follows = [
        follow
        for follow in following
        if follow.analyst_id not in paid_analyst_ids
        and getattr(follow.analyst, "analyst_profile", None) is not None
        and follow.analyst.analyst_profile.paid_predictions_enabled
        and follow.analyst.analyst_profile.paid_predictions_price > 0
        and (not selected_capper or follow.analyst.username == selected_capper)
    ]
    paid_upgrade_ids = [follow.analyst_id for follow in paid_upgrade_follows]
    locked_paid_counts = {
        row["author_id"]: row["total"]
        for row in PredictionCoupon.objects.filter(
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            is_paid=True,
            author_id__in=paid_upgrade_ids,
        )
        .values("author_id")
        .annotate(total=Count("id"))
    }

    author_counts = {
        row["author_id"]: row["total"]
        for row in PredictionCoupon.objects.filter(
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            is_paid=False,
            author_id__in=following_ids,
        )
        .values("author_id")
        .annotate(total=Count("id"))
    }

    capper_params = request.GET.copy()
    capper_params.pop("page", None)
    capper_params.pop("capper", None)
    feed_all_cappers_url = _feed_url(request, capper_params)

    for follow in following:
        profile = getattr(follow.analyst, "analyst_profile", None)
        follow.feed_name = (
            profile.display_name
            if profile and profile.display_name
            else follow.analyst.get_full_name() or follow.analyst.username
        )
        follow.feed_avatar_url = profile.avatar.url if profile and profile.avatar else ""
        follow.feed_initial = (follow.feed_name or follow.analyst.username or "К")[0].upper()
        follow.feed_predictions_count = author_counts.get(follow.analyst_id, 0)
        follow.feed_locked_paid_count = locked_paid_counts.get(follow.analyst_id, 0)
        follow.feed_profile_url = reverse(
            "front:expert_profile",
            kwargs={"username": follow.analyst.username},
        )

        follow_params = capper_params.copy()
        follow_params["capper"] = follow.analyst.username
        follow.feed_filter_url = _feed_url(request, follow_params)

    feed_all_cappers_count = sum(author_counts.values())
    params_without_page = request.GET.copy()
    params_without_page.pop("page", None)
    pagination_query = params_without_page.urlencode()

    active_filter_count = sum(
        [
            bool(selected_capper),
            only_live,
            only_today,
            active_status != "all",
        ]
    )

    return render(
        request,
        "front/following_feed.html",
        {
            "page_obj": page_obj,
            "following": following,
            "paid_subscriptions": paid_subscriptions,
            "has_feed_sources": bool(following or paid_subscriptions),
            "following_count": len(following),
            "paid_subscriptions_count": len(paid_subscriptions),
            "paid_predictions": paid_predictions,
            "paid_predictions_count": paid_predictions_count,
            "paid_upgrade_offers": paid_upgrade_follows,
            "paid_upgrade_offers_count": len(paid_upgrade_follows),
            "feed_total_count": paginator.count + paid_predictions_count,
            "feed_predictions_count": paginator.count,
            "status_tabs": _status_tabs(request, counts, active_status),
            "active_status": active_status,
            "active_sort": active_sort,
            "sort_options": FEED_SORT_OPTIONS,
            "selected_capper": selected_capper,
            "only_live": only_live,
            "only_today": only_today,
            "pagination_query": pagination_query,
            "active_filter_count": active_filter_count,
            "feed_all_cappers_url": feed_all_cappers_url,
            "feed_all_cappers_count": feed_all_cappers_count,
            "filter_action_url": request.path,
            "adv_placement": "sidebar",
            "hide_footer": True,
            "predictions_filter_collapsed": prediction_filter_collapsed(request),
        },
    )
