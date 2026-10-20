from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from cappers.ratelimit import rate_limited
from cabinet.models import DailyTask
from cabinet.paid_predictions import user_can_view_paid_coupon
from cabinet.services.daily_tasks import record_daily_task_action
from game.models import PredictionCoupon

from .metrics import (
    get_prediction_metrics,
    record_coupon_open,
    increment_prediction_shares,
    refresh_prediction_metrics,
    toggle_prediction_favorite_metric,
    toggle_prediction_like_metric,
)
from .models import PredictionFavorite, PredictionLike


OWN_LIKE_ERROR = "Нельзя лайкать собственный прогноз."
OWN_FAVORITE_ERROR = "Нельзя сохранять собственный прогноз в избранное."


def _accessible_published_prediction(user, prediction_id: int) -> PredictionCoupon:
    prediction = get_object_or_404(
        PredictionCoupon,
        pk=prediction_id,
        published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
    )
    if (
        prediction.audience == PredictionCoupon.Audience.PAID
        and not user_can_view_paid_coupon(user, prediction)
    ):
        raise Http404("Прогноз не найден.")
    return prediction


@login_required
@require_POST
def open_prediction(request, prediction_id: int):
    from .templatetags.prediction_reactions import coupon_opens_label

    if rate_limited(f"coupon-open:{request.user.pk}", limit=120, window=60):
        return JsonResponse({"ok": False}, status=429)
    prediction = _accessible_published_prediction(request.user, prediction_id)
    metrics = record_coupon_open(request.user, prediction) or get_prediction_metrics(prediction.pk)
    return JsonResponse({
        "ok": True, "unique_opens_count": metrics.unique_opens_count,
        "label": coupon_opens_label(metrics.unique_opens_count),
    })


@login_required
@require_POST
def toggle_prediction_like(request, prediction_id: int):
    prediction = _accessible_published_prediction(request.user, prediction_id)
    if prediction.author_id == request.user.id:
        PredictionLike.objects.filter(prediction=prediction, user=request.user).delete()
        metrics = refresh_prediction_metrics(prediction.pk)
        return JsonResponse(
            {
                "ok": False,
                "active": False,
                "count": metrics.likes_count if metrics else 0,
                "error": OWN_LIKE_ERROR,
            },
            status=403,
        )

    active, metrics = toggle_prediction_like_metric(prediction, request.user)
    return JsonResponse(
        {
            "ok": True,
            "active": active,
            "count": metrics.likes_count,
        }
    )


@login_required
@require_POST
def toggle_prediction_favorite(request, prediction_id: int):
    prediction = _accessible_published_prediction(request.user, prediction_id)
    if prediction.author_id == request.user.id:
        PredictionFavorite.objects.filter(prediction=prediction, user=request.user).delete()
        metrics = refresh_prediction_metrics(prediction.pk)
        return JsonResponse(
            {
                "ok": False,
                "active": False,
                "count": metrics.favorites_count if metrics else 0,
                "error": OWN_FAVORITE_ERROR,
            },
            status=403,
        )

    active, metrics = toggle_prediction_favorite_metric(prediction, request.user)
    if active:
        record_daily_task_action(
            request.user,
            DailyTask.TaskType.ADD_FAVORITE,
            related_obj=prediction,
        )
    return JsonResponse(
        {
            "ok": True,
            "active": active,
            "count": metrics.favorites_count,
        }
    )


@require_POST
def share_prediction(request, prediction_id: int):
    prediction = _accessible_published_prediction(request.user, prediction_id)
    metrics = increment_prediction_shares(prediction.pk)
    return JsonResponse(
        {
            "ok": True,
            "shares_count": metrics.shares_count,
        }
    )
