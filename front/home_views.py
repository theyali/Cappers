from django.db.models import Count, Q
from django.shortcuts import render
from django.utils import timezone

from cabinet.models import AnalystProfile, User
from front.models import Article
from front.views import _initials, _top_experts
from game.models import Match, Prediction, PredictionCoupon


HOME_PREDICTIONS_LIMIT = 8
HOME_ARTICLES_LIMIT = 6
HOME_MATCHES_LIMIT = 9
HOME_EXPERTS_LIMIT = 6


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


def _best_home_experts() -> list[dict]:
    profiles = list(
        AnalystProfile.objects.filter(
            is_public=True,
            user__role=User.Role.ANALYST,
        )
        .select_related("user")
        .annotate(
            followers_count=Count("user__analyst_followers", distinct=True),
            predictions_count=Count(
                "user__prediction_coupons__predictions",
                filter=Q(
                    user__prediction_coupons__published_status=PredictionCoupon.PublishedStatus.PUBLISHED
                ),
                distinct=True,
            ),
            wins_count=Count(
                "user__prediction_coupons__predictions",
                filter=Q(
                    user__prediction_coupons__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
                    user__prediction_coupons__predictions__state_status=Prediction.StateStatus.WIN,
                ),
                distinct=True,
            ),
            losses_count=Count(
                "user__prediction_coupons__predictions",
                filter=Q(
                    user__prediction_coupons__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
                    user__prediction_coupons__predictions__state_status=Prediction.StateStatus.LOSE,
                ),
                distinct=True,
            ),
        )
        .order_by("-wins_count", "-followers_count", "-is_verified", "-created_at")[:HOME_EXPERTS_LIMIT]
    )

    experts = []
    for profile in profiles:
        settled = profile.wins_count + profile.losses_count
        win_rate = round(profile.wins_count / settled * 100) if settled else 0
        name = profile.display_name or profile.user.get_full_name() or profile.user.username
        experts.append(
            {
                "name": name,
                "username": profile.user.username,
                "initials": _initials(name),
                "avatar_url": profile.avatar.url if profile.avatar else "",
                "verified": profile.is_verified,
                "followers": profile.followers_count,
                "predictions": profile.predictions_count,
                "wins": profile.wins_count,
                "win_rate": win_rate,
            }
        )
    return experts


def _league_rating(match: Match) -> int:
    """Return league importance from normalized data or provider payload."""
    league = match.league
    if league is None:
        return 0

    values = [getattr(league, "rating", None)]
    raw_data = league.raw_data if isinstance(league.raw_data, dict) else {}
    values.extend(
        raw_data.get(key)
        for key in ("rating", "league_rating", "league_rank", "rank")
    )

    match_raw = match.raw_data if isinstance(match.raw_data, dict) else {}
    raw_league = match_raw.get("league") if isinstance(match_raw.get("league"), dict) else {}
    values.extend(
        raw_league.get(key)
        for key in ("rating", "league_rating", "league_rank", "rank")
    )

    for value in values:
        if value in (None, ""):
            continue
        try:
            return int(float(value))
        except (TypeError, ValueError):
            continue
    return 0


def _important_home_matches() -> list[Match]:
    now = timezone.now()
    matches = list(
        Match.objects.filter(sync_scope=Match.SyncScope.PREMATCH)
        .filter(Q(starts_at__gte=now) | Q(starts_at__isnull=True))
        .select_related(
            "sport",
            "league__country",
            "home_team",
            "away_team",
            "odds",
        )
        .order_by("-last_seen_at", "-created_at", "-id")
    )

    important = [match for match in matches if _league_rating(match) > 0]
    important.sort(
        key=lambda match: (
            -_league_rating(match),
            match.starts_at.timestamp() if match.starts_at else float("inf"),
            match.id,
        )
    )

    selected = important[:HOME_MATCHES_LIMIT]
    if len(selected) < HOME_MATCHES_LIMIT:
        selected_ids = {match.id for match in selected}
        selected.extend(
            match
            for match in matches
            if match.id not in selected_ids
        )

    return selected[:HOME_MATCHES_LIMIT]


def index(request):
    return render(
        request,
        "front/index.html",
        {
            "latest_predictions": _latest_home_predictions(),
            "top_experts": _top_experts(),
            "best_experts": _best_home_experts(),
            "latest_articles": Article.objects.filter(is_published=True).order_by("-created_at", "-id")[:HOME_ARTICLES_LIMIT],
            "important_matches": _important_home_matches(),
        },
    )
