from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from cabinet.models import AnalystFollow
from game.models import Prediction, PredictionCoupon

from .models import PredictionFavorite, PredictionLike
from .views import PREDICTION_STATUS_FILTERS, _initials


PREDICTIONS_PAGE_SIZE = 24


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
            "match__league__country",
            "match__home_team",
            "match__away_team",
        )
        .annotate(likes_count=Count("likes", distinct=True))
    )


@ensure_csrf_cookie
def predictions(request):
    active_status = request.GET.get("status", "all")
    valid_statuses = {key for key, _ in PREDICTION_STATUS_FILTERS}
    if active_status not in valid_statuses:
        active_status = "all"

    published = Prediction.objects.filter(
        coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
    )
    counts = published.aggregate(
        total=Count("id"),
        pending=Count("id", filter=Q(state_status="") | Q(state_status__isnull=True)),
        win=Count("id", filter=Q(state_status=Prediction.StateStatus.WIN)),
        lose=Count("id", filter=Q(state_status=Prediction.StateStatus.LOSE)),
        refund=Count("id", filter=Q(state_status=Prediction.StateStatus.REFUND)),
    )

    queryset = _published_queryset()
    if active_status == "pending":
        queryset = queryset.filter(Q(state_status="") | Q(state_status__isnull=True))
    elif active_status != "all":
        queryset = queryset.filter(state_status=active_status)

    following_ids = _following_ids(request.user)
    if request.user.is_authenticated:
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

    count_map = {
        "all": counts["total"],
        "pending": counts["pending"],
        Prediction.StateStatus.WIN: counts["win"],
        Prediction.StateStatus.LOSE: counts["lose"],
        Prediction.StateStatus.REFUND: counts["refund"],
    }
    status_tabs = [
        {"key": key, "label": label, "count": count_map.get(key, 0)}
        for key, label in PREDICTION_STATUS_FILTERS
    ]

    return render(
        request,
        "front/predictions.html",
        {
            "page_obj": page_obj,
            "status_tabs": status_tabs,
            "active_status": active_status,
            "total_predictions": counts["total"],
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
