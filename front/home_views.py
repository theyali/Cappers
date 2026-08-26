from django.shortcuts import render
from django.utils import timezone

from cabinet.models import AnalystProfile
from front.models import Article
from front.views import _initials, _top_experts
from game.models import Prediction, PredictionCoupon


HOME_PREDICTIONS_LIMIT = 8
HOME_ARTICLES_LIMIT = 6


def _logo_url(primary: str, related) -> str:
    if primary:
        return primary
    if related is not None and getattr(related, "logo", ""):
        return related.logo
    return ""


def _state_label(prediction: Prediction) -> tuple[str, str]:
    if prediction.state_status == Prediction.StateStatus.WIN:
        return "Выигрыш", "win"
    if prediction.state_status == Prediction.StateStatus.LOSE:
        return "Проигрыш", "lose"
    if prediction.state_status == Prediction.StateStatus.REFUND:
        return "Возврат", "refund"
    return "Ожидает", "pending"


def _latest_home_predictions() -> list[dict]:
    queryset = (
        Prediction.objects.filter(
            coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        )
        .select_related(
            "coupon__author",
            "coupon__author__analyst_profile",
            "match__sport",
            "match__league",
            "match__home_team",
            "match__away_team",
        )
        .order_by("-coupon__published_at", "-coupon__created_at", "-created_at", "-id")[:HOME_PREDICTIONS_LIMIT]
    )

    cards = []
    for prediction in queryset:
        author = prediction.coupon.author
        try:
            profile = author.analyst_profile
        except AnalystProfile.DoesNotExist:
            profile = None

        expert_name = (
            profile.display_name
            if profile and profile.display_name
            else author.get_full_name() or author.username
        )
        match = prediction.match
        status_label, status_key = _state_label(prediction)
        starts_at = "Время не указано"
        if match.starts_at:
            starts_at = timezone.localtime(match.starts_at).strftime("%d.%m · %H:%M")

        cards.append(
            {
                "url": match.get_absolute_url(),
                "sport": (match.sport.name_ru if match.sport and match.sport.name_ru else "Футбол"),
                "league": match.league_name or "Лига",
                "league_logo": match.league.logo if match.league and match.league.logo else "",
                "home_name": match.home_team_name or "Хозяева",
                "away_name": match.away_team_name or "Гости",
                "home_logo": _logo_url(match.home_team_logo, match.home_team),
                "away_logo": _logo_url(match.away_team_logo, match.away_team),
                "score": match.score or "",
                "pick": prediction.selection,
                "market": prediction.market,
                "coefficient": prediction.coefficient,
                "starts_at": starts_at,
                "note": prediction.comment,
                "expert": expert_name,
                "expert_username": author.username,
                "expert_initials": _initials(expert_name),
                "expert_avatar_url": profile.avatar.url if profile and profile.avatar else "",
                "expert_verified": bool(profile and profile.is_verified),
                "status_label": status_label,
                "status_key": status_key,
            }
        )
    return cards


def index(request):
    return render(
        request,
        "front/index.html",
        {
            "latest_predictions": _latest_home_predictions(),
            "top_experts": _top_experts(),
            "latest_articles": Article.objects.filter(is_published=True).order_by("-created_at", "-id")[:HOME_ARTICLES_LIMIT],
        },
    )
