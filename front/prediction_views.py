from decimal import Decimal, InvalidOperation

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import (
    Case,
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    IntegerField,
    OuterRef,
    Q,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from cabinet.models import AnalystFollow
from game.models import Prediction, PredictionCoupon

from .models import PredictionFavorite, PredictionLike
from .views import PREDICTION_STATUS_FILTERS, _initials


PREDICTIONS_PAGE_SIZE = 24
SORT_OPTIONS = (
    ("new", "Новые"),
    ("roi", "Лучший ROI"),
    ("popular", "Самые популярные"),
)
SETTLED_COUPON_STATES = (
    PredictionCoupon.StateStatus.WIN,
    PredictionCoupon.StateStatus.LOSE,
    PredictionCoupon.StateStatus.REFUND,
)


def _following_ids(user) -> set[int]:
    if not user.is_authenticated:
        return set()
    return set(
        AnalystFollow.objects.filter(follower=user).values_list("analyst_id", flat=True)
    )


def _decorate_predictions(request, predictions, following_ids: set[int] | None = None):
    predictions = list(predictions)
    prediction_ids = [prediction.pk for prediction in predictions]
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

    for prediction in predictions:
        author = prediction.coupon.author
        profile = getattr(author, "analyst_profile", None)
        name = (
            profile.display_name
            if profile and profile.display_name
            else author.get_full_name() or author.username
        )
        prediction.expert_name = name
        prediction.expert_initials = _initials(name)
        prediction.expert_avatar_url = profile.avatar.url if profile and profile.avatar else ""
        prediction.expert_verified = bool(profile and profile.is_verified)
        prediction.is_liked = prediction.pk in liked_ids
        prediction.is_favorite = prediction.pk in favorite_ids
        prediction.is_own = bool(request.user.is_authenticated and author.pk == request.user.pk)
        prediction.is_following_author = author.pk in following_ids and not prediction.is_own

    return predictions


def _published_queryset():
    return (
        Prediction.objects.filter(
            coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        )
        .select_related(
            "coupon__author",
            "coupon__author__analyst_profile",
            "match__sport",
            "match__league__country",
            "match__home_team",
            "match__away_team",
        )
        .annotate(
            likes_count=Count("likes", distinct=True),
            favorites_count=Count("favorites", distinct=True),
        )
    )


def _parse_decimal(value: str | None) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", "."))
    except InvalidOperation:
        return None


def _author_roi_subquery():
    money_field = DecimalField(max_digits=18, decimal_places=4)
    profit_expression = Case(
        When(
            state_status=PredictionCoupon.StateStatus.WIN,
            then=F("possible_payout") - F("total_stake"),
        ),
        When(
            state_status=PredictionCoupon.StateStatus.LOSE,
            then=-F("total_stake"),
        ),
        default=Value(Decimal("0")),
        output_field=money_field,
    )
    return (
        PredictionCoupon.objects.filter(
            author_id=OuterRef("coupon__author_id"),
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status__in=SETTLED_COUPON_STATES,
            total_stake__gt=0,
        )
        .values("author_id")
        .annotate(
            roi_profit=Sum(profit_expression),
            roi_stake=Sum("total_stake"),
        )
        .annotate(
            roi_value=ExpressionWrapper(
                F("roi_profit") * Value(Decimal("100")) / F("roi_stake"),
                output_field=DecimalField(max_digits=12, decimal_places=4),
            )
        )
        .values("roi_value")[:1]
    )


def _filter_options(published, selected_sport: str):
    sports = list(
        published.exclude(match__sport_id__isnull=True)
        .values("match__sport_id", "match__sport__name_ru", "match__sport__name")
        .distinct()
        .order_by("match__sport__name_ru", "match__sport__name")
    )

    leagues_source = published.exclude(match__league_id__isnull=True)
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
        published.values(
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


def _status_tabs(request, counts: dict, active_status: str):
    count_map = {
        "all": counts["total"],
        "pending": counts["pending"],
        Prediction.StateStatus.WIN: counts["win"],
        Prediction.StateStatus.LOSE: counts["lose"],
        Prediction.StateStatus.REFUND: counts["refund"],
    }

    tabs = []
    for key, label in PREDICTION_STATUS_FILTERS:
        params = request.GET.copy()
        params["status"] = key
        params.pop("page", None)
        tabs.append(
            {
                "key": key,
                "label": label,
                "count": count_map.get(key, 0),
                "href": f"?{params.urlencode()}",
                "active": active_status == key,
            }
        )
    return tabs


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

    published = Prediction.objects.filter(
        coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
    )

    filtered = published
    if selected_sport.isdigit():
        filtered = filtered.filter(match__sport_id=int(selected_sport))
    if selected_league.isdigit():
        filtered = filtered.filter(match__league_id=int(selected_league))
    if selected_capper:
        filtered = filtered.filter(coupon__author__username=selected_capper)
    if coefficient_min is not None:
        filtered = filtered.filter(coefficient__gte=coefficient_min)
    if coefficient_max is not None:
        filtered = filtered.filter(coefficient__lte=coefficient_max)
    if only_live:
        filtered = filtered.filter(match__sync_scope="live")
    if only_today:
        filtered = filtered.filter(match__starts_at__date=timezone.localdate())

    counts = filtered.aggregate(
        total=Count("id"),
        pending=Count("id", filter=Q(state_status="") | Q(state_status__isnull=True)),
        win=Count("id", filter=Q(state_status=Prediction.StateStatus.WIN)),
        lose=Count("id", filter=Q(state_status=Prediction.StateStatus.LOSE)),
        refund=Count("id", filter=Q(state_status=Prediction.StateStatus.REFUND)),
    )

    queryset = _published_queryset()
    if selected_sport.isdigit():
        queryset = queryset.filter(match__sport_id=int(selected_sport))
    if selected_league.isdigit():
        queryset = queryset.filter(match__league_id=int(selected_league))
    if selected_capper:
        queryset = queryset.filter(coupon__author__username=selected_capper)
    if coefficient_min is not None:
        queryset = queryset.filter(coefficient__gte=coefficient_min)
    if coefficient_max is not None:
        queryset = queryset.filter(coefficient__lte=coefficient_max)
    if only_live:
        queryset = queryset.filter(match__sync_scope="live")
    if only_today:
        queryset = queryset.filter(match__starts_at__date=timezone.localdate())

    if active_status == "pending":
        queryset = queryset.filter(Q(state_status="") | Q(state_status__isnull=True))
    elif active_status != "all":
        queryset = queryset.filter(state_status=active_status)

    following_ids = _following_ids(request.user)
    if active_sort == "roi":
        roi_field = DecimalField(max_digits=12, decimal_places=4)
        queryset = queryset.annotate(
            author_roi=Coalesce(
                Subquery(_author_roi_subquery(), output_field=roi_field),
                Value(Decimal("0")),
                output_field=roi_field,
            )
        ).order_by(
            "-author_roi",
            "-likes_count",
            "-coupon__published_at",
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
            "-coupon__published_at",
            "-created_at",
        )
    elif request.user.is_authenticated:
        queryset = queryset.annotate(
            feed_priority=Case(
                When(coupon__author=request.user, then=Value(0)),
                When(coupon__author_id__in=following_ids, then=Value(1)),
                default=Value(2),
                output_field=IntegerField(),
            )
        ).order_by(
            "feed_priority",
            "-coupon__published_at",
            "-coupon__created_at",
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

    sports, leagues, cappers = _filter_options(published, selected_sport)

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


@login_required
@ensure_csrf_cookie
def favorites(request):
    following_ids = _following_ids(request.user)
    queryset = (
        _published_queryset()
        .filter(favorites__user=request.user)
        .order_by("-favorites__created_at", "-created_at")
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


def _published_prediction(prediction_id: int) -> Prediction:
    return get_object_or_404(
        Prediction,
        pk=prediction_id,
        coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
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
