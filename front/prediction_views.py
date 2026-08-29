import json
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import (
    Case,
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    IntegerField,
    Prefetch,
    Q,
    Value,
    When,
)
from django.http import HttpResponsePermanentRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from cabinet.models import AnalystFollow
from game.models import Prediction, PredictionCoupon, Sport

from .expert_ranking import ranked_expert_profiles
from .models import PredictionFavorite, PredictionLike
from .prediction_metrics import annotate_author_roi
from .views import PREDICTION_STATUS_FILTERS, _initials


PREDICTIONS_PAGE_SIZE = 24
TOP_EXPERTS_LIMIT = 10
SORT_OPTIONS = (
    ("new", "Новые"),
    ("roi", "Лучший ROI"),
    ("popular", "Самые популярные"),
)
PREDICTION_FILTER_COLLAPSED_SESSION_KEY = "front.prediction_filter_collapsed"


def prediction_filter_collapsed(request) -> bool:
    return bool(request.session.get(PREDICTION_FILTER_COLLAPSED_SESSION_KEY))


@require_POST
def prediction_filter_state(request):
    raw_value = request.POST.get("collapsed", "")
    collapsed = str(raw_value).lower() in {"1", "true", "yes", "on"}
    request.session[PREDICTION_FILTER_COLLAPSED_SESSION_KEY] = collapsed
    request.session.modified = True
    return JsonResponse({"ok": True, "collapsed": collapsed})


def _following_ids(user) -> set[int]:
    if not user.is_authenticated:
        return set()
    return set(
        AnalystFollow.objects.filter(follower=user).values_list("analyst_id", flat=True)
    )


def _positions_queryset():
    return Prediction.objects.select_related(
        "match__sport",
        "match__league__country",
        "match__home_team",
        "match__away_team",
    ).order_by("id")


def _combined_coefficient_expression():
    return Case(
        When(
            total_stake__gt=0,
            then=ExpressionWrapper(
                F("possible_payout") / F("total_stake"),
                output_field=DecimalField(max_digits=12, decimal_places=4),
            ),
        ),
        default=Value(Decimal("0")),
        output_field=DecimalField(max_digits=12, decimal_places=4),
    )


def _normalized_coefficient(value) -> Decimal:
    try:
        return Decimal(value or 0).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0.00")


def _published_queryset():
    queryset = (
        PredictionCoupon.objects.filter(
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        )
        .select_related(
            "author",
            "author__analyst_profile",
        )
        .prefetch_related(
            Prefetch("predictions", queryset=_positions_queryset(), to_attr="card_positions")
        )
        .annotate(
            likes_count=Count("likes", distinct=True),
            favorites_count=Count("favorites", distinct=True),
            positions_count=Count("predictions", distinct=True),
            combined_coefficient=_combined_coefficient_expression(),
        )
    )
    return annotate_author_roi(
        queryset,
        author_outer_ref="author_id",
        annotation_name="author_roi",
    )


def _prediction_card(coupon: PredictionCoupon):
    positions = list(getattr(coupon, "card_positions", []) or [])
    if not positions:
        return None

    item = positions[0]
    count = getattr(coupon, "positions_count", None) or len(positions)
    combined_coefficient = getattr(coupon, "combined_coefficient", None)
    if combined_coefficient is None:
        if coupon.total_stake:
            combined_coefficient = coupon.possible_payout / coupon.total_stake
        else:
            combined_coefficient = Decimal("0")
    combined_coefficient = _normalized_coefficient(combined_coefficient)

    selection = item.selection
    market = item.market
    if count > 1:
        market = f"Экспресс · {count} игр"
        selection = f"{item.selection} + ещё {count - 1}"

    return SimpleNamespace(
        id=coupon.id,
        coupon=coupon,
        match=item.match,
        market=market,
        selection=selection,
        coefficient=combined_coefficient,
        state_status=coupon.state_status,
        created_at=coupon.published_at or coupon.created_at,
        positions_count=count,
        likes_count=getattr(coupon, "likes_count", 0),
        favorites_count=getattr(coupon, "favorites_count", 0),
        author_roi=getattr(coupon, "author_roi", Decimal("0")),
    )


def _decorate_predictions(request, predictions, following_ids: set[int] | None = None):
    coupons = list(predictions)
    prediction_ids = [coupon.pk for coupon in coupons]
    liked_ids = set()
    favorite_ids = set()
    following_ids = following_ids if following_ids is not None else _following_ids(request.user)

    if request.user.is_authenticated and prediction_ids:
        liked_ids = set(
            PredictionLike.objects.filter(
                user=request.user,
                prediction_id__in=prediction_ids,
            ).values_list("prediction_id", flat=True)
        )
        favorite_ids = set(
            PredictionFavorite.objects.filter(
                user=request.user,
                prediction_id__in=prediction_ids,
            ).values_list("prediction_id", flat=True)
        )

    cards = []
    for coupon in coupons:
        card = _prediction_card(coupon)
        if card is None:
            continue

        author = coupon.author
        profile = getattr(author, "analyst_profile", None)
        name = (
            profile.display_name
            if profile and profile.display_name
            else author.get_full_name() or author.username
        )
        card.expert_name = name
        card.expert_initials = _initials(name)
        card.expert_avatar_url = profile.avatar.url if profile and profile.avatar else ""
        card.expert_verified = bool(profile and profile.is_verified)
        card.is_liked = coupon.pk in liked_ids
        card.is_favorite = coupon.pk in favorite_ids
        card.is_own = bool(request.user.is_authenticated and author.pk == request.user.pk)
        card.is_following_author = author.pk in following_ids and not card.is_own
        cards.append(card)

    return cards


def _parse_decimal(value: str | None) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", "."))
    except InvalidOperation:
        return None


def _prediction_sport_path(sport_code: str | None = None) -> str:
    if sport_code:
        return reverse("front:predictions_by_sport", kwargs={"sport_code": sport_code})
    return reverse("front:predictions")


def _clean_prediction_params(params, *, drop_page: bool = True):
    cleaned = params.copy()
    cleaned.pop("sport", None)
    if drop_page:
        cleaned.pop("page", None)
    if cleaned.get("sort") == "new":
        cleaned.pop("sort", None)
    if cleaned.get("status") == "all":
        cleaned.pop("status", None)
    return cleaned


def _url_with_query(path: str, params) -> str:
    query = params.urlencode()
    return f"{path}?{query}" if query else path


def _sport_from_filter(value: str) -> Sport | None:
    if not value:
        return None
    queryset = Sport.objects.all()
    if value.isdigit():
        return queryset.filter(pk=int(value)).first()
    return queryset.filter(code__iexact=value).first()


def _resolve_sport_route(request, sport_code: str | None):
    query_has_sport = "sport" in request.GET
    query_sport = request.GET.get("sport", "").strip()

    if sport_code:
        route_sport = get_object_or_404(Sport, code__iexact=sport_code)
        if query_has_sport:
            requested_sport = _sport_from_filter(query_sport)
            params = _clean_prediction_params(request.GET, drop_page=False)
            target_path = _prediction_sport_path(requested_sport.code if requested_sport else None)
            return requested_sport, HttpResponsePermanentRedirect(
                _url_with_query(target_path, params)
            )
        if route_sport.code != sport_code:
            params = _clean_prediction_params(request.GET, drop_page=False)
            return route_sport, HttpResponsePermanentRedirect(
                _url_with_query(_prediction_sport_path(route_sport.code), params)
            )
        return route_sport, None

    if query_has_sport:
        requested_sport = _sport_from_filter(query_sport)
        params = _clean_prediction_params(request.GET, drop_page=False)
        target_path = _prediction_sport_path(requested_sport.code if requested_sport else None)
        return requested_sport, HttpResponsePermanentRedirect(
            _url_with_query(target_path, params)
        )

    return None, None


def _filter_options(published_items, selected_sport: str):
    sports = list(
        published_items.exclude(match__sport_id__isnull=True)
        .values(
            "match__sport_id",
            "match__sport__code",
            "match__sport__name_ru",
            "match__sport__name",
        )
        .distinct()
        .order_by("match__sport__name_ru", "match__sport__name")
    )

    leagues_source = published_items.exclude(match__league_id__isnull=True)
    if selected_sport.isdigit():
        leagues_source = leagues_source.filter(match__sport_id=int(selected_sport))
    leagues = list(
        leagues_source.values(
            "match__league_id",
            "match__league__name_ru",
            "match__league__name",
        )
        .distinct()
        .order_by("match__league__name_ru", "match__league__name")
    )

    cappers = list(
        published_items.values(
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


def _sport_tabs(request, published_items, active_sport: Sport | None):
    params = _clean_prediction_params(request.GET)
    params.pop("league", None)

    rows = list(
        published_items.exclude(match__sport_id__isnull=True)
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

    tabs = [
        {
            "code": "",
            "label": "Все",
            "count": all_count,
            "href": _url_with_query(_prediction_sport_path(), params),
            "active": active_sport is None,
        }
    ]
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


def _status_tabs(request, counts: dict, active_status: str):
    count_map = {
        "all": counts["total"],
        "pending": counts["pending"],
        PredictionCoupon.StateStatus.WIN: counts["win"],
        PredictionCoupon.StateStatus.LOSE: counts["lose"],
        PredictionCoupon.StateStatus.REFUND: counts["refund"],
    }

    tabs = []
    for key, label in PREDICTION_STATUS_FILTERS:
        params = _clean_prediction_params(request.GET)
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


def _top_experts_tab(request, *, active: bool, count: int) -> dict:
    params = _clean_prediction_params(request.GET)
    if active:
        params.pop("top", None)
    else:
        params["top"] = "1"
    return {
        "active": active,
        "count": count,
        "href": _url_with_query(request.path, params),
    }


def _apply_position_filters(queryset, *, selected_sport, selected_league, only_live, only_today):
    if selected_sport.isdigit():
        queryset = queryset.filter(predictions__match__sport_id=int(selected_sport))
    if selected_league.isdigit():
        queryset = queryset.filter(predictions__match__league_id=int(selected_league))
    if only_live:
        queryset = queryset.filter(predictions__match__sync_scope="live")
    if only_today:
        queryset = queryset.filter(predictions__match__starts_at__date=timezone.localdate())
    return queryset.distinct()


def _has_seo_facets(request) -> bool:
    values = request.GET
    if values.get("status") not in (None, "", "all"):
        return True
    if values.get("sort") not in (None, "", "new"):
        return True
    for key in ("league", "capper", "coef_min", "coef_max"):
        if values.get(key):
            return True
    for key in ("live", "today", "top"):
        if values.get(key) == "1":
            return True
    return False


def _prediction_seo(request, active_sport: Sport | None, page_number: int):
    if active_sport:
        sport_name = active_sport.name_ru or active_sport.name or active_sport.code
        topic = sport_name.lower()
        page_heading = f"Прогнозы на {topic}"
        title = f"Прогнозы на {topic} от капперов — статистика и коэффициенты | КапперХаб"
        description = (
            f"Прогнозы на {topic} от капперов КапперХаб: коэффициенты, статистика экспертов, "
            "результаты прогнозов и удобные фильтры по лигам и статусам."
        )
        canonical_path = _prediction_sport_path(active_sport.code)
    else:
        page_heading = "Все прогнозы на спорт"
        title = "Прогнозы на спорт от капперов — статистика и коэффициенты | КапперХаб"
        description = (
            "Прогнозы на спорт от капперов КапперХаб: футбол, хоккей, баскетбол, теннис, "
            "коэффициенты, результаты и подтверждённая статистика экспертов."
        )
        canonical_path = _prediction_sport_path()

    has_facets = _has_seo_facets(request)
    canonical_url = request.build_absolute_uri(canonical_path)
    if page_number > 1 and not has_facets:
        canonical_url = f"{canonical_url}?page={page_number}"
        title = f"{title} — страница {page_number}"

    home_url = request.build_absolute_uri(reverse("front:index"))
    predictions_url = request.build_absolute_uri(_prediction_sport_path())
    breadcrumbs = [
        {
            "@type": "ListItem",
            "position": 1,
            "name": "КапперХаб",
            "item": home_url,
        },
        {
            "@type": "ListItem",
            "position": 2,
            "name": "Прогнозы на спорт",
            "item": predictions_url,
        },
    ]
    if active_sport:
        breadcrumbs.append(
            {
                "@type": "ListItem",
                "position": 3,
                "name": page_heading,
                "item": request.build_absolute_uri(_prediction_sport_path(active_sport.code)),
            }
        )

    schema = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": page_heading,
        "description": description,
        "url": canonical_url,
        "isPartOf": {
            "@type": "WebSite",
            "name": "КапперХаб",
            "url": home_url,
        },
        "breadcrumb": {
            "@type": "BreadcrumbList",
            "itemListElement": breadcrumbs,
        },
    }

    return {
        "page_heading": page_heading,
        "page_intro": (
            f"Прогнозы капперов на {(active_sport.name_ru or active_sport.name).lower()}: "
            "сравнивайте коэффициенты, статистику экспертов и результаты опубликованных прогнозов."
            if active_sport
            else "Ищите прогнозы по спорту, лиге, эксперту и коэффициенту. Можно отдельно смотреть live, матчи на сегодня и уже рассчитанные прогнозы."
        ),
        "seo_meta": {
            "title": title,
            "description": description,
            "robots": "noindex,follow" if has_facets else "index,follow",
            "canonical_url": canonical_url,
            "og_title": title,
            "og_description": description,
            "og_type": "website",
            "twitter_card": "summary",
            "schema_json_ld": json.dumps(schema, ensure_ascii=False),
        },
    }


@ensure_csrf_cookie
def predictions(request, sport_code: str | None = None):
    active_sport, redirect_response = _resolve_sport_route(request, sport_code)
    if redirect_response:
        return redirect_response

    active_status = request.GET.get("status", "all")
    valid_statuses = {key for key, _ in PREDICTION_STATUS_FILTERS}
    if active_status not in valid_statuses:
        active_status = "all"

    active_sort = request.GET.get("sort", "new")
    valid_sorts = {key for key, _ in SORT_OPTIONS}
    if active_sort not in valid_sorts:
        active_sort = "new"

    selected_sport = str(active_sport.pk) if active_sport else ""
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

    params_without_page = _clean_prediction_params(request.GET)
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

    seo_context = _prediction_seo(request, active_sport, page_obj.number)

    return render(
        request,
        "front/predictions.html",
        {
            "page_obj": page_obj,
            "status_tabs": _status_tabs(request, counts, active_status),
            "sport_tabs": _sport_tabs(request, published_items, active_sport),
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
            "predictions_filter_collapsed": prediction_filter_collapsed(request),
            **seo_context,
        },
    )


@ensure_csrf_cookie
def prediction_detail(request, prediction_id: int):
    coupon = get_object_or_404(
        PredictionCoupon.objects.filter(
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        )
        .select_related("author", "author__analyst_profile")
        .prefetch_related(
            Prefetch("predictions", queryset=_positions_queryset(), to_attr="detail_positions")
        )
        .annotate(
            likes_count=Count("likes", distinct=True),
            favorites_count=Count("favorites", distinct=True),
        ),
        pk=prediction_id,
    )
    positions = list(getattr(coupon, "detail_positions", []) or [])

    total_coefficient = Decimal("1")
    for position in positions:
        total_coefficient *= position.coefficient
    total_coefficient = _normalized_coefficient(total_coefficient if positions else 0)

    author = coupon.author
    profile = getattr(author, "analyst_profile", None)
    expert_name = (
        profile.display_name
        if profile and profile.display_name
        else author.get_full_name() or author.username
    )

    is_liked = False
    is_favorite = False
    if request.user.is_authenticated:
        is_liked = PredictionLike.objects.filter(prediction=coupon, user=request.user).exists()
        is_favorite = PredictionFavorite.objects.filter(prediction=coupon, user=request.user).exists()

    return render(
        request,
        "front/prediction_detail.html",
        {
            "coupon": coupon,
            "positions": positions,
            "total_coefficient": total_coefficient,
            "expert_name": expert_name,
            "expert_initials": _initials(expert_name),
            "expert_avatar_url": profile.avatar.url if profile and profile.avatar else "",
            "expert_verified": bool(profile and profile.is_verified),
            "is_liked": is_liked,
            "is_favorite": is_favorite,
        },
    )


@login_required
@ensure_csrf_cookie
def favorites(request):
    following_ids = _following_ids(request.user)
    queryset = (
        _published_queryset()
        .filter(favorites__user=request.user)
        .order_by("-favorites__created_at", "-created_at")
        .distinct()
    )
    paginator = Paginator(queryset, PREDICTIONS_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))
    page_obj.object_list = _decorate_predictions(
        request,
        page_obj.object_list,
        following_ids=following_ids,
    )

    return render(
        request,
        "front/favorites.html",
        {
            "page_obj": page_obj,
            "total_predictions": paginator.count,
        },
    )


def _published_prediction(prediction_id: int) -> PredictionCoupon:
    return get_object_or_404(
        PredictionCoupon,
        pk=prediction_id,
        published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
    )


@login_required
@require_POST
def toggle_prediction_like(request, prediction_id: int):
    prediction = _published_prediction(prediction_id)
    reaction, created = PredictionLike.objects.get_or_create(
        prediction=prediction,
        user=request.user,
    )
    active = created
    if not created:
        reaction.delete()
        active = False

    return JsonResponse(
        {
            "ok": True,
            "active": active,
            "count": PredictionLike.objects.filter(prediction=prediction).count(),
        }
    )


@login_required
@require_POST
def toggle_prediction_favorite(request, prediction_id: int):
    prediction = _published_prediction(prediction_id)
    favorite, created = PredictionFavorite.objects.get_or_create(
        prediction=prediction,
        user=request.user,
    )
    active = created
    if not created:
        favorite.delete()
        active = False

    return JsonResponse({"ok": True, "active": active})
