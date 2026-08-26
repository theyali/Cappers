from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie

from cabinet.models import AnalystFollow
from game.models import Prediction

from .prediction_views import (
    PREDICTIONS_PAGE_SIZE,
    _decorate_predictions,
    _published_queryset,
    _status_tabs,
)
from .views import PREDICTION_STATUS_FILTERS


FEED_SORT_OPTIONS = (
    ("new", "Новые"),
    ("popular", "Популярные"),
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

    selected_capper = request.GET.get("capper", "").strip()
    if selected_capper and selected_capper not in followed_usernames:
        selected_capper = ""

    only_live = request.GET.get("live") == "1"
    only_today = request.GET.get("today") == "1"

    queryset = _published_queryset().filter(coupon__author_id__in=following_ids)
    if selected_capper:
        queryset = queryset.filter(coupon__author__username=selected_capper)
    if only_live:
        queryset = queryset.filter(match__sync_scope="live")
    if only_today:
        queryset = queryset.filter(match__starts_at__date=timezone.localdate())

    counts = queryset.aggregate(
        total=Count("id"),
        pending=Count("id", filter=Q(state_status="") | Q(state_status__isnull=True)),
        win=Count("id", filter=Q(state_status=Prediction.StateStatus.WIN)),
        lose=Count("id", filter=Q(state_status=Prediction.StateStatus.LOSE)),
        refund=Count("id", filter=Q(state_status=Prediction.StateStatus.REFUND)),
    )

    if active_status == "pending":
        queryset = queryset.filter(Q(state_status="") | Q(state_status__isnull=True))
    elif active_status != "all":
        queryset = queryset.filter(state_status=active_status)

    if active_sort == "popular":
        queryset = queryset.order_by(
            "-likes_count",
            "-favorites_count",
            "-coupon__published_at",
            "-created_at",
        )
    else:
        queryset = queryset.order_by(
            "-coupon__published_at",
            "-coupon__created_at",
            "-created_at",
        )

    paginator = Paginator(queryset, PREDICTIONS_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))
    page_obj.object_list = _decorate_predictions(
        request,
        page_obj.object_list,
        following_ids=following_ids,
    )

    author_counts = {
        row["coupon__author_id"]: row["total"]
        for row in _published_queryset()
        .filter(coupon__author_id__in=following_ids)
        .values("coupon__author_id")
        .annotate(total=Count("id"))
    }
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

    params_without_page = request.GET.copy()
    params_without_page.pop("page", None)
    pagination_query = params_without_page.urlencode()

    active_filter_count = sum(
        [
            bool(selected_capper),
            only_live,
            only_today,
            active_status != "all",
            active_sort != "new",
        ]
    )

    return render(
        request,
        "front/following_feed.html",
        {
            "page_obj": page_obj,
            "following": following,
            "following_count": len(following),
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
        },
    )
