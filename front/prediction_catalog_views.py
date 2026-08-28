from django.core.paginator import Paginator
from django.db.models import Case, Count, ExpressionWrapper, F, IntegerField, Q, Value, When
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie

from game.models import Prediction, PredictionCoupon

from .expert_ranking import ranked_expert_profiles
from .prediction_views import (
    PREDICTIONS_PAGE_SIZE,
    SORT_OPTIONS,
    _apply_position_filters,
    _decorate_predictions,
    _filter_options,
    _following_ids,
    _parse_decimal,
    _published_queryset,
    _status_tabs,
)
from .views import PREDICTION_STATUS_FILTERS


TOP_EXPERTS_LIMIT = 10


def _top_experts_tab(request, *, active: bool, count: int) -> dict:
    params = request.GET.copy()
    params.pop("page", None)
    if active:
        params.pop("top", None)
    else:
        params["top"] = "1"
    query = params.urlencode()
    return {
        "active": active,
        "count": count,
        "href": f"?{query}" if query else "?",
    }


@ensure_csrf_cookie
def predictions(request):
    active_status = request.GET.get("status", "all")
    valid_statuses = {key for key, _ in PREDICTION_STATUS_FILTERS}
    if active_status not in valid_statuses:
        active_status = "all"

    active_sort = request.GET.get("sort", "new")
    valid_sorts = {key for key, _ in SORT_OPTIONS}
    if active_sort not in valid_sorts:
        active_sort = "new"

    selected_sport = request.GET.get("sport", "").strip()
    selected_league = request.GET.get("league", "").strip()
    selected_capper = request.GET.get("capper", "").strip()
    coefficient_min = _parse_decimal(request.GET.get("coef_min"))
    coefficient_max = _parse_decimal(request.GET.get("coef_max"))
    only_live = request.GET.get("live") == "1"
    only_today = request.GET.get("today") == "1"
    top_experts_only = request.GET.get("top") == "1"

    top_profiles = ranked_expert_profiles(limit=TOP_EXPERTS_LIMIT)
    top_expert_ids = [profile.user_id for profile in top_profiles]

    published_items = Prediction.objects.filter(
        coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
    )

    filtered = _published_queryset()
    filtered = _apply_position_filters(
        filtered,
        selected_sport=selected_sport,
        selected_league=selected_league,
        only_live=only_live,
        only_today=only_today,
    )
    if selected_capper:
        filtered = filtered.filter(author__username=selected_capper)
    if coefficient_min is not None:
        filtered = filtered.filter(combined_coefficient__gte=coefficient_min)
    if coefficient_max is not None:
        filtered = filtered.filter(combined_coefficient__lte=coefficient_max)

    top_filtered = filtered.filter(author_id__in=top_expert_ids)
    top_experts_count = top_filtered.count()
    if top_experts_only:
        filtered = top_filtered

    counts = filtered.aggregate(
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

    queryset = filtered
    if active_status == "pending":
        queryset = queryset.filter(state_status=PredictionCoupon.StateStatus.PENDING)
    elif active_status != "all":
        queryset = queryset.filter(state_status=active_status)

    following_ids = _following_ids(request.user)
    if active_sort == "roi":
        queryset = queryset.order_by(
            "-author_roi",
            "-likes_count",
            "-published_at",
            "-created_at",
        )
    elif active_sort == "popular":
        queryset = queryset.annotate(
            popularity_score=ExpressionWrapper(
                F("likes_count") * Value(2) + F("favorites_count") * Value(3),
                output_field=IntegerField(),
            )
        ).order_by(
            "-popularity_score",
            "-likes_count",
            "-published_at",
            "-created_at",
        )
    elif request.user.is_authenticated:
        queryset = queryset.annotate(
            feed_priority=Case(
                When(author=request.user, then=Value(0)),
                When(author_id__in=following_ids, then=Value(1)),
                default=Value(2),
                output_field=IntegerField(),
            )
        ).order_by(
            "feed_priority",
            "-published_at",
            "-created_at",
        )
    else:
        queryset = queryset.order_by("-published_at", "-created_at")

    paginator = Paginator(queryset, PREDICTIONS_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))
    page_obj.object_list = _decorate_predictions(
        request,
        page_obj.object_list,
        following_ids=following_ids,
    )

    sports, leagues, cappers = _filter_options(published_items, selected_sport)

    params_without_page = request.GET.copy()
    params_without_page.pop("page", None)
    pagination_query = params_without_page.urlencode()

    active_filter_count = sum(
        [
            bool(selected_sport),
            bool(selected_league),
            bool(selected_capper),
            coefficient_min is not None,
            coefficient_max is not None,
            only_live,
            only_today,
            active_status != "all",
        ]
    )

    return render(
        request,
        "front/predictions.html",
        {
            "page_obj": page_obj,
            "status_tabs": _status_tabs(request, counts, active_status),
            "top_experts_tab": _top_experts_tab(
                request,
                active=top_experts_only,
                count=top_experts_count,
            ),
            "top_experts_only": top_experts_only,
            "active_status": active_status,
            "active_sort": active_sort,
            "sort_options": SORT_OPTIONS,
            "total_predictions": counts["total"],
            "filtered_predictions": paginator.count,
            "sports": sports,
            "leagues": leagues,
            "cappers": cappers,
            "selected_sport": selected_sport,
            "selected_league": selected_league,
            "selected_capper": selected_capper,
            "coefficient_min": request.GET.get("coef_min", ""),
            "coefficient_max": request.GET.get("coef_max", ""),
            "only_live": only_live,
            "only_today": only_today,
            "pagination_query": pagination_query,
            "active_filter_count": active_filter_count,
        },
    )
