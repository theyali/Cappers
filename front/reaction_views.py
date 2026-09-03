from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from cabinet.paid_predictions import user_can_view_paid_predictions
from game.models import PredictionCoupon

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
        and not user_can_view_paid_predictions(user, prediction.author)
    ):
        raise Http404("Прогноз не найден.")
    return prediction


@login_required
@require_POST
def toggle_prediction_like(request, prediction_id: int):
    prediction = _accessible_published_prediction(request.user, prediction_id)
    if prediction.author_id == request.user.id:
        PredictionLike.objects.filter(prediction=prediction, user=request.user).delete()
        return JsonResponse(
            {
                "ok": False,
                "active": False,
                "count": PredictionLike.objects.filter(prediction=prediction).count(),
                "error": OWN_LIKE_ERROR,
            },
            status=403,
        )

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
    prediction = _accessible_published_prediction(request.user, prediction_id)
    if prediction.author_id == request.user.id:
        PredictionFavorite.objects.filter(prediction=prediction, user=request.user).delete()
        return JsonResponse(
            {
                "ok": False,
                "active": False,
                "count": PredictionFavorite.objects.filter(prediction=prediction).count(),
                "error": OWN_FAVORITE_ERROR,
            },
            status=403,
        )

    favorite, created = PredictionFavorite.objects.get_or_create(
        prediction=prediction,
        user=request.user,
    )
    active = created
    if not created:
        favorite.delete()
        active = False

    return JsonResponse(
        {
            "ok": True,
            "active": active,
            "count": PredictionFavorite.objects.filter(prediction=prediction).count(),
        }
    )
