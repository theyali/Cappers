from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from game.models import Prediction, PredictionCoupon

from .models import AnalystFollow, AnalystProfile, User


def _initials(name: str) -> str:
    parts = [part for part in (name or "").split() if part]
    return "".join(part[0] for part in parts[:2]).upper() or "К"


@ensure_csrf_cookie
def expert_profile(request, username: str):
    profile = get_object_or_404(
        AnalystProfile.objects.select_related("user"),
        user__username=username,
        user__role=User.Role.ANALYST,
        is_public=True,
    )
    analyst = profile.user

    published = Prediction.objects.filter(
        coupon__author=analyst,
        coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
    )
    stats = published.aggregate(
        predictions=Count("id"),
        wins=Count("id", filter=Q(state_status=Prediction.StateStatus.WIN)),
        losses=Count("id", filter=Q(state_status=Prediction.StateStatus.LOSE)),
        refunds=Count("id", filter=Q(state_status=Prediction.StateStatus.REFUND)),
    )
    settled = stats["wins"] + stats["losses"]
    win_rate = round(stats["wins"] / settled * 100) if settled else 0
    followers_count = AnalystFollow.objects.filter(analyst=analyst).count()

    is_following = False
    if request.user.is_authenticated and request.user.pk != analyst.pk:
        is_following = AnalystFollow.objects.filter(
            follower=request.user,
            analyst=analyst,
        ).exists()

    latest_predictions = list(
        published.select_related(
            "match__league__country",
            "match__home_team",
            "match__away_team",
        ).order_by("-coupon__published_at", "-created_at")[:12]
    )

    name = profile.display_name or analyst.get_full_name() or analyst.username
    return render(
        request,
        "cabinet/expert_profile.html",
        {
            "expert": analyst,
            "analyst_profile": profile,
            "expert_name": name,
            "expert_initials": _initials(name),
            "followers_count": followers_count,
            "predictions_count": stats["predictions"],
            "wins_count": stats["wins"],
            "losses_count": stats["losses"],
            "refunds_count": stats["refunds"],
            "win_rate": win_rate,
            "is_following": is_following,
            "is_self": request.user.is_authenticated and request.user.pk == analyst.pk,
            "latest_predictions": latest_predictions,
        },
    )


@login_required
@require_POST
def toggle_follow(request, user_id: int):
    analyst = get_object_or_404(
        User,
        pk=user_id,
        role=User.Role.ANALYST,
        analyst_profile__is_public=True,
    )
    if analyst.pk == request.user.pk:
        return JsonResponse(
            {"ok": False, "error": "Нельзя подписаться на самого себя."},
            status=400,
        )

    follow, created = AnalystFollow.objects.get_or_create(
        follower=request.user,
        analyst=analyst,
    )
    active = created
    if not created:
        follow.delete()
        active = False

    return JsonResponse(
        {
            "ok": True,
            "active": active,
            "followers_count": AnalystFollow.objects.filter(analyst=analyst).count(),
            "message": "Вы подписаны." if active else "Подписка отменена.",
        }
    )
