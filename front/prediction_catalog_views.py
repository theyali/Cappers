import json
from decimal import Decimal

from django.core.paginator import Paginator
from django.db.models import Case, Count, ExpressionWrapper, F, IntegerField, Q, Value, When
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.views.decorators.csrf import ensure_csrf_cookie

from game.models import Prediction, PredictionCoupon

from .expert_ranking import ranked_expert_profiles
from .prediction_views import (
    PREDICTIONS_PAGE_SIZE,
    SORT_OPTIONS,
    TOP_EXPERTS_LIMIT,
    _clean_prediction_params,
    _decorate_predictions,
    _following_ids,
    _parse_decimal,
    _prediction_seo,
    _prediction_sport_path,
    _published_queryset,
    _resolve_sport_route,
    _status_tabs,
    _top_experts_tab,
    _url_with_query,
    prediction_filter_collapsed,
)


def _counted_published_items(published_items):
    return published_items.annotate(
        coupon_positions_count=Count("coupon__predictions", distinct=True),
    )


def _filter_options(published_items, selected_sport: str, *, express_only: bool):
    counted_items = _counted_published_items(published_items)
    single_items = counted_items.filter(coupon_positions_count=1)

    sports = list(
        single_items.exclude(match__sport_id__isnull=True)
        .values(
            "match__sport_id",
            "match__sport__code",
            "match__sport__name_ru",
            "match__sport__name",
        )
        .distinct()
        .order_by("match__sport__name_ru", "match__sport__name")
    )

    if express_only:
        option_source = counted_items.filter(coupon_positions_count__gt=1)
    elif selected_sport.isdigit():
        option_source = single_items.filter(match__sport_id=int(selected_sport))
    else:
        option_source = published_items

    leagues = list(
        option_source.exclude(match__league_id__isnull=True)
        .values(
            "match__league_id",
            "match__league__name_ru",
            "match__league__name",
        )
        .distinct()
        .order_by("match__league__name_ru", "match__league__name")
    )

    cappers = list(
        option_source.values(
            "coupon__author__username",
            "coupon__author__analyst_profile__display_name",
        )
        .distinct()
        .order_by(
            "coupon__author__analyst_profile__display_name",
            "coupon__author__username",
        )
    )

    return sports, leagues, cappers


def _sport_tabs(request, published_items, active_sport, *, express_only: bool):
    params = _clean_prediction_params(request.GET)
    params.pop("league", None)
    params.pop("express", None)

    counted_items = _counted_published_items(published_items)
    single_items = counted_items.filter(coupon_positions_count=1)

    rows = list(
        single_items.exclude(match__sport_id__isnull=True)
        .values(
            "match__sport_id",
            "match__sport__code",
            "match__sport__name_ru",
            "match__sport__name",
        )
        .annotate(count=Count("coupon_id", distinct=True))
        .order_by("match__sport__name_ru", "match__sport__name")
    )
    all_count = published_items.values("coupon_id").distinct().count()
    express_count = (
        counted_items.filter(coupon_positions_count__gt=1)
        .values("coupon_id")
        .distinct()
        .count()
    )

    tabs = [
        {
            "code": "",
            "label": "Все",
            "count": all_count,
            "href": _url_with_query(_prediction_sport_path(), params),
            "active": active_sport is None and not express_only,
        }
    ]

    express_params = params.copy()
    express_params["express"] = "1"
    tabs.append(
        {
            "code": "express",
            "label": "Экспрессы",
            "count": express_count,
            "href": _url_with_query(_prediction_sport_path(), express_params),
            "active": express_only,
        }
    )

    for row in rows:
        code = row["match__sport__code"]
        tabs.append(
            {
                "code": code,
                "label": row["match__sport__name_ru"] or row["match__sport__name"] or code,
                "count": row["count"],
                "href": _url_with_query(_prediction_sport_path(code), params),
                "active": bool(active_sport and active_sport.pk == row["match__sport_id"]),
            }
        )
    return tabs


def _apply_position_filters(
    queryset,
    *,
    selected_sport,
    selected_league,
    only_live,
    only_today,
    express_only,
):
    if express_only:
        queryset = queryset.filter(positions_count__gt=1)
    elif selected_sport.isdigit():
        queryset = queryset.filter(
            positions_count=1,
            predictions__match__sport_id=int(selected_sport),
        )

    if selected_league.isdigit():
        queryset = queryset.filter(predictions__match__league_id=int(selected_league))
    if only_live:
        queryset = queryset.filter(predictions__match__sync_scope="live")
    if only_today:
        from django.utils import timezone

        queryset = queryset.filter(predictions__match__starts_at__date=timezone.localdate())
    return queryset.distinct()


def _catalog_seo_context(request, active_sport, page_number: int, *, express_only: bool):
    context = _prediction_seo(request, active_sport, page_number)
    if not express_only:
        return context

    title = "Экспрессы от капперов — коэффициенты и результаты | КапперХаб"
    description = (
        "Экспрессы капперов КапперХаб: комбинированные прогнозы из нескольких матчей, "
        "общие коэффициенты и результаты расчёта."
    )
    context["page_heading"] = "Экспрессы"
    context["page_intro"] = (
        "Купоны из двух и более игр вынесены отдельно от прогнозов по конкретным видам спорта."
    )

    meta = context["seo_meta"]
    meta["title"] = title
    meta["description"] = description
    meta["robots"] = "noindex,follow"
    meta["og_title"] = title
    meta["og_description"] = description

    try:
        schema = json.loads(meta.get("schema_json_ld") or "{}")
    except (TypeError, ValueError):
        schema = {}
    if schema:
        schema["name"] = "Экспрессы"
        schema["description"] = description
        meta["schema_json_ld"] = json.dumps(schema, ensure_ascii=False)
    return context


@ensure_csrf_cookie
def predictions(request, sport_code: str | None = None):
    active_sport, redirect_response = _resolve_sport_route(request, sport_code)
    if redirect_response:
        return redirect_response

    if active_sport and request.GET.get("express") == "1":
        params = request.GET.copy()
        params.pop("express", None)
        return HttpResponseRedirect(
            _url_with_query(_prediction_sport_path(active_sport.code), params)
        )

    active_status = request.GET.get("status", "all")
    from .views import PREDICTION_STATUS_FILTERS

    valid_statuses = {key for key, _ in PREDICTION_STATUS_FILTERS}
    if active_status not in valid_statuses:
        active_status = "all"

    active_sort = request.GET.get("sort", "new")
    valid_sorts = {key for key, _ in SORT_OPTIONS}
    if active_sort not in valid_sorts:
        active_sort = "new"

    selected_sport = str(active_sport.pk) if active_sport else ""
    express_only = active_sport is None and request.GET.get("express") == "1"
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
        express_only=express_only,
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

    sports, leagues, cappers = _filter_options(
        published_items,
        selected_sport,
        express_only=express_only,
    )

    params_without_page = _clean_prediction_params(request.GET)
    if active_sport:
        params_without_page.pop("express", None)
    pagination_query = params_without_page.urlencode()

    active_filter_count = sum(
        [
            bool(selected_sport) or express_only,
            bool(selected_league),
            bool(selected_capper),
            coefficient_min is not None,
            coefficient_max is not None,
            only_live,
            only_today,
            active_status != "all",
        ]
    )

    seo_context = _catalog_seo_context(
        request,
        active_sport,
        page_obj.number,
        express_only=express_only,
    )

    return render(
        request,
        "front/predictions.html",
        {
            "page_obj": page_obj,
            "status_tabs": _status_tabs(request, counts, active_status),
            "sport_tabs": _sport_tabs(
                request,
                published_items,
                active_sport,
                express_only=express_only,
            ),
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
            "selected_sport_code": active_sport.code if active_sport else "",
            "express_only": express_only,
            "selected_league": selected_league,
            "selected_capper": selected_capper,
            "coefficient_min": request.GET.get("coef_min", ""),
            "coefficient_max": request.GET.get("coef_max", ""),
            "only_live": only_live,
            "only_today": only_today,
            "pagination_query": pagination_query,
            "active_filter_count": active_filter_count,
            "filter_action_url": _prediction_sport_path(active_sport.code if active_sport else None),
            "all_predictions_url": _prediction_sport_path(),
            "adv_placement": "sidebar",
            "hide_footer": True,
            "predictions_filter_collapsed": prediction_filter_collapsed(request),
            **seo_context,
        },
    )
