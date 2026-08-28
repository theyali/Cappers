from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from front.models import PredictionFavorite, PredictionLike
from notifications.models import MatchWatch

from .achievements import build_achievement_overview
from .models import AnalystFollow, MatchPredictionRequest, User


def _prediction_title(prediction) -> str:
    return f"Прогноз #{prediction.pk}"


def _match_title(match) -> str:
    home = match.home_team_name or "Хозяева"
    away = match.away_team_name or "Гости"
    return f"{home} — {away}"


def user_profile(request, username: str):
    user = get_object_or_404(User, username=username, is_active=True)
    if user.is_analyst:
        return redirect("cabinet:expert_profile", username=user.username)

    likes = PredictionLike.objects.filter(user=user).select_related("prediction")
    favorites = PredictionFavorite.objects.filter(user=user).select_related("prediction")
    follows = AnalystFollow.objects.filter(follower=user).select_related(
        "analyst", "analyst__analyst_profile"
    )
    match_watches = MatchWatch.objects.filter(user=user)
    prediction_requests = MatchPredictionRequest.objects.filter(user=user).select_related(
        "match__home_team", "match__away_team", "match__league"
    )

    recent_activity = []
    for item in likes[:6]:
        recent_activity.append(
            {
                "created_at": item.created_at,
                "kind": "Лайк",
                "title": _prediction_title(item.prediction),
                "description": "Понравился прогноз каппера",
                "url": reverse("front:prediction_detail", kwargs={"prediction_id": item.prediction_id}),
            }
        )
    for item in favorites[:6]:
        recent_activity.append(
            {
                "created_at": item.created_at,
                "kind": "Сохранение",
                "title": _prediction_title(item.prediction),
                "description": "Сохранил прогноз в избранное",
                "url": reverse("front:prediction_detail", kwargs={"prediction_id": item.prediction_id}),
            }
        )
    for item in follows[:6]:
        profile = getattr(item.analyst, "analyst_profile", None)
        analyst_name = (
            profile.display_name
            if profile and profile.display_name
            else item.analyst.get_full_name() or item.analyst.username
        )
        recent_activity.append(
            {
                "created_at": item.created_at,
                "kind": "Подписка",
                "title": analyst_name,
                "description": f"Подписался на @{item.analyst.username}",
                "url": reverse("cabinet:expert_profile", kwargs={"username": item.analyst.username}),
            }
        )
    for item in prediction_requests[:6]:
        recent_activity.append(
            {
                "created_at": item.created_at,
                "kind": "Хочу прогноз",
                "title": _match_title(item.match),
                "description": "Запросил прогноз на матч",
                "url": item.match.get_absolute_url(),
            }
        )

    recent_activity.sort(key=lambda item: item["created_at"], reverse=True)
    recent_activity = recent_activity[:12]

    achievement_overview = build_achievement_overview(user)
    unlocked_achievements = [
        item for item in achievement_overview["items"] if item["unlocked"]
    ]

    display_name = user.get_full_name().strip() or user.username
    return render(
        request,
        "cabinet/user_profile.html",
        {
            "profile_user": user,
            "display_name": display_name,
            "initials": "".join(part[0] for part in display_name.split()[:2]).upper() or user.username[:1].upper(),
            "match_watches_count": match_watches.count(),
            "favorites_count": favorites.count(),
            "likes_count": likes.count(),
            "following_count": follows.count(),
            "prediction_requests_count": prediction_requests.count(),
            "recent_activity": recent_activity,
            "unlocked_achievements": unlocked_achievements,
            "achievement_total": achievement_overview["total_count"],
            "achievement_unlocked_count": achievement_overview["unlocked_count"],
            "is_self": request.user.is_authenticated and request.user.pk == user.pk,
        },
    )
