from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, ExpressionWrapper, F, IntegerField, Q, Value
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie

from game.models import Prediction, PredictionCoupon

from .prediction_views import (
    PREDICTIONS_PAGE_SIZE,
    SORT_OPTIONS,
    _apply_position_filters,
    _decorate_predictions,
    _filter_options,
    _following_ids,
    _parse_decimal,
    _published_queryset,
    _sport_from_filter,
)
from .views import PREDICTION_STATUS_FILTERS


def _query_without_page(request):
    params = request.GET.copy()
    params.pop("page", None)
    if params.get("sort") == "new":
        params.pop("sort", None)
    if params.get("status") == "all":
        params.pop("status", None)
    return params


def _url_with_query(path, params):
    query = params.urlencode()
    return f"{path}?{query}" if query else path


def _favorites_status_tabs(request, counts, active_status):
    count_map = {
        "all": counts["total"],
        "pending": counts["pending"],
        PredictionCoupon.StateStatus.WIN: counts["win"],
        PredictionCoupon.StateStatus.LOSE: counts["lose"],
        PredictionCoupon.StateStatus.REFUND: counts["refund"],
    }
    tabs = []
    for key, label in PREDICTION_STATUS_FILTERS:
        params = _query_without_page(request)
        if key == "all":
            params.pop("status", None)
        else:
            params["status"] = key
        tabs.append(
            {
                "key": key,
                "label": label,
                "count": count_map.get(key, 0),
                "href": _url_with_query(request.path, params),
                "active": active_status == key,
            }
        )
    return tabs


def _favorites_sport_tabs(request, favorite_positions, active_sport):
    rows = list(
        favorite_positions.exclude(match__sport_id__isnull=True)
        .values(
            "match__sport_id",
            "match__sport__code",
            "match__sport__name_ru",
            "match__sport__name",
        )
        .annotate(count=Count("coupon_id", distinct=True))
        .order_by("match__sport__name_ru", "match__sport__name")
    )
    all_count = favorite_positions.values("coupon_id").distinct().count()

    params = _query_without_page(request)
    params.pop("sport", None)
    params.pop("league", None)
    tabs = [
        {
            "code": "",
            "label": "Все",
            "count": all_count,
            "href": _url_with_query(request.path, params),
            "active": active_sport is None,
        }
    ]
    for row in rows:
        tab_params = params.copy()
        tab_params["sport"] = str(row["match__sport_id"])
        tabs.append(
            {
                "code": row["match__sport__code"],
                "label": row["match__sport__name_ru"]
                or row["match__sport__name"]
                or row["match__sport__code"],
                "count": row["count"],
                "href": _url_with_query(request.path, tab_params),
                "active": bool(active_sport and active_sport.pk == row["match__sport_id"]),
            }
        )
    return tabs


@login_required
@ensure_csrf_cookie
def favorites(request):
    active_status = request.GET.get("status", "all")
    valid_statuses = {key for key, _ in PREDICTION_STATUS_FILTERS}
    if active_status not in valid_statuses:
        active_status = "all"

    active_sort = request.GET.get("sort", "new")
    valid_sorts = {key for key, _ in SORT_OPTIONS}
    if active_sort not in valid_sorts:
        active_sort = "new"

    active_sport = _sport_from_filter(request.GET.get("sport", "").strip())
    selected_sport = str(active_sport.pk) if active_sport else ""
    selected_league = request.GET.get("league", "").strip()
    selected_capper = request.GET.get("capper", "").strip()
    coefficient_min = _parse_decimal(request.GET.get("coef_min"))
    coefficient_max = _parse_decimal(request.GET.get("coef_max"))
    only_live = request.GET.get("live") == "1"
    only_today = request.GET.get("today") == "1"

    favorite_positions = Prediction.objects.filter(
        coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        coupon__audience=PredictionCoupon.Audience.FREE,
        coupon__favorites__user=request.user,
    ).distinct()

    base_queryset = (
        _published_queryset()
        .filter(favorites__user=request.user)
        .distinct()
    )
    total_predictions = base_queryset.count()

    filtered = _apply_position_filters(
        base_queryset,
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
    else:
        queryset = queryset.order_by("-favorites__created_at", "-created_at")

    following_ids = _following_ids(request.user)
    paginator = Paginator(queryset, PREDICTIONS_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))
    page_obj.object_list = _decorate_predictions(
        request,
        page_obj.object_list,
        following_ids=following_ids,
    )

    sports, leagues, cappers = _filter_options(favorite_positions, selected_sport)
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

    pagination_params = _query_without_page(request)
    pagination_query = pagination_params.urlencode()
    favorites_url = reverse("front:favorites")

    return render(
        request,
        "front/favorites.html",
        {
            "page_obj": page_obj,
            "total_predictions": total_predictions,
            "filtered_predictions": paginator.count,
            "status_tabs": _favorites_status_tabs(request, counts, active_status),
            "sport_tabs": _favorites_sport_tabs(request, favorite_positions, active_sport),
            "active_status": active_status,
            "active_sort": active_sort,
            "sort_options": SORT_OPTIONS,
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
            "active_filter_count": active_filter_count,
            "filter_action_url": favorites_url,
            "reset_url": favorites_url,
            "pagination_query": pagination_query,
            "adv_placement": "sidebar",
            "hide_footer": True,
        },
    )
