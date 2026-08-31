from decimal import Decimal

from django.db.models import Count, Prefetch, Q
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie

from cabinet.achievements import build_achievement_badges
from cabinet.expert_profile_views import _recommended_experts
from cabinet.models import AnalystProfile, User
from front.expert_ranking import ranked_expert_profiles
from front.models import Article
from front.prediction_views import _decorate_predictions, _published_queryset
from front.views import DEMO_EXPERTS, _best_streaks_for_authors, _initials
from game.models import Match, Prediction, PredictionCoupon
from game.views import _match_winner_odds
from notifications.models import MatchWatch


HOME_PREDICTIONS_LIMIT = 8
HOME_BEST_PREDICTIONS_LIMIT = 10
HOME_ARTICLES_LIMIT = 6
HOME_MATCHES_LIMIT = 12
HOME_EXPERTS_LIMIT = 8
HOME_MATCH_CANDIDATE_LIMIT = 120


def _logo_url(primary: str, related) -> str:
    if primary:
        return primary
    if related is not None and getattr(related, "logo", ""):
        return related.logo
    return ""


def _state_label(prediction: PredictionCoupon) -> tuple[str, str]:
    if prediction.state_status == PredictionCoupon.StateStatus.WIN:
        return "Выигрыш", "win"
    if prediction.state_status == PredictionCoupon.StateStatus.LOSE:
        return "Проигрыш", "lose"
    if prediction.state_status == PredictionCoupon.StateStatus.REFUND:
        return "Возврат", "refund"
    return "Ожидает", "pending"


def _latest_home_predictions() -> list[dict]:
    positions = Prediction.objects.select_related(
        "match__sport",
        "match__league",
        "match__home_team",
        "match__away_team",
    ).order_by("id")
    queryset = list(
        PredictionCoupon.objects.filter(
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        )
        .select_related("author", "author__analyst_profile")
        .prefetch_related(
            Prefetch("predictions", queryset=positions, to_attr="home_positions")
        )
        .annotate(positions_count=Count("predictions", distinct=True))
        .order_by("-published_at", "-created_at", "-id")[:HOME_PREDICTIONS_LIMIT]
    )

    cards = []
    for prediction in queryset:
        positions_list = list(getattr(prediction, "home_positions", []) or [])
        if not positions_list:
            continue
        item = positions_list[0]
        author = prediction.author
        try:
            profile = author.analyst_profile
        except AnalystProfile.DoesNotExist:
            profile = None

        expert_name = (
            profile.display_name
            if profile and profile.display_name
            else author.get_full_name() or author.username
        )
        match = item.match
        status_label, status_key = _state_label(prediction)
        starts_at = "Время не указано"
        if match.starts_at:
            starts_at = timezone.localtime(match.starts_at).strftime("%d.%m · %H:%M")

        count = prediction.positions_count or len(positions_list)
        if prediction.total_stake:
            coefficient = prediction.possible_payout / prediction.total_stake
        else:
            coefficient = Decimal("0")
        pick = item.selection
        market = item.market
        if count > 1:
            pick = f"{item.selection} + ещё {count - 1}"
            market = f"Экспресс · {count} игр"

        cards.append(
            {
                "id": prediction.id,
                "url": match.get_absolute_url(),
                "sport": (
                    match.sport.name_ru
                    if match.sport and match.sport.name_ru
                    else "Спорт"
                ),
                "league": match.league_name or "Лига",
                "league_logo": (
                    match.league.logo if match.league and match.league.logo else ""
                ),
                "home_name": match.home_team_name or "Хозяева",
                "away_name": match.away_team_name or "Гости",
                "home_logo": _logo_url(match.home_team_logo, match.home_team),
                "away_logo": _logo_url(match.away_team_logo, match.away_team),
                "score": match.score or "",
                "pick": pick,
                "market": market,
                "coefficient": coefficient.quantize(Decimal("0.01")),
                "confidence": prediction.confidence,
                "positions_count": count,
                "starts_at": starts_at,
                "expert": expert_name,
                "expert_username": author.username,
                "expert_initials": _initials(expert_name),
                "expert_avatar_url": (
                    profile.avatar.url if profile and profile.avatar else ""
                ),
                "expert_verified": bool(profile and profile.is_verified),
                "status_label": status_label,
                "status_key": status_key,
            }
        )
    return cards


def _best_home_predictions(request):
    queryset = _published_queryset().filter(
        state_status=PredictionCoupon.StateStatus.WIN,
    ).order_by(
        "-combined_coefficient",
        "-published_at",
        "-created_at",
        "-id",
    )[:HOME_BEST_PREDICTIONS_LIMIT]
    return _decorate_predictions(request, queryset)


def _top_home_experts(profiles) -> list[dict]:
    if not profiles:
        return DEMO_EXPERTS

    experts = []
    for profile in profiles[:7]:
        name = profile.display_name or profile.user.get_full_name() or profile.user.username
        experts.append(
            {
                "name": name,
                "username": profile.user.username,
                "followers": profile.followers_count,
                "initials": _initials(name),
                "verified": profile.is_verified,
                "avatar_url": profile.avatar.url if profile.avatar else "",
            }
        )
    return experts


def _best_home_experts(request, profiles) -> list[dict]:
    profiles = list(profiles[:HOME_EXPERTS_LIMIT])

    best_streaks = _best_streaks_for_authors([profile.user_id for profile in profiles])
    following_ids = set()
    if request.user.is_authenticated:
        following_ids = set(
            request.user.analyst_follows.filter(
                analyst_id__in=[profile.user_id for profile in profiles]
            ).values_list("analyst_id", flat=True)
        )

    experts = []
    for profile in profiles:
        settled = profile.wins_count + profile.losses_count
        win_rate = round(profile.wins_count / settled * 100) if settled else 0
        name = profile.display_name or profile.user.get_full_name() or profile.user.username
        unlocked_achievements = build_achievement_badges(
            predictions_count=profile.publications_count,
            wins_count=profile.wins_count,
            overall_roi=profile.author_roi,
            followers_count=profile.followers_count,
            best_win_streak=best_streaks.get(profile.user_id, 0),
            is_verified=profile.is_verified,
        )
        experts.append(
            {
                "id": profile.user_id,
                "name": name,
                "username": profile.user.username,
                "initials": _initials(name),
                "avatar_url": profile.avatar.url if profile and profile.avatar else "",
                "verified": profile.is_verified,
                "roi": profile.author_roi,
                "ranking_score": profile.ranking_score,
                "followers": profile.followers_count,
                "predictions": profile.publications_count,
                "publications": profile.publications_count,
                "sports": profile.sports_count,
                "recent_publications": profile.recent_publications_count,
                "wins": profile.wins_count,
                "win_rate": win_rate,
                "last_publication_at": profile.last_publication_at,
                "joined_at": profile.created_at,
                "latest_achievements": list(reversed(unlocked_achievements[-5:])),
                "is_self": (
                    request.user.is_authenticated
                    and request.user.id == profile.user_id
                ),
                "is_following": profile.user_id in following_ids,
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
    raw_league = (
        match_raw.get("league")
        if isinstance(match_raw.get("league"), dict)
        else {}
    )
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


def _home_match_has_quick_odds_q() -> Q:
    return (
        Q(odds__home_win_bet__isnull=False)
        | Q(odds__x_bet__isnull=False)
        | Q(odds__away_win_bet__isnull=False)
        | Q(odds__goals_over_2_5__isnull=False)
        | Q(odds__goals_under_2_5__isnull=False)
        | Q(odds__btts_yes__isnull=False)
    )


def _home_match_queryset(now):
    return (
        Match.objects.filter(sync_scope=Match.SyncScope.PREMATCH)
        .filter(Q(starts_at__gte=now) | Q(starts_at__isnull=True))
        .select_related(
            "sport",
            "league__country",
            "home_team",
            "away_team",
            "odds",
        )
        .annotate(
            predictions_count=Count(
                "predictions__coupon",
                filter=Q(
                    predictions__coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED
                ),
                distinct=True,
            )
        )
    )


def _important_home_matches(request, can_write_coupon: bool = False) -> list[Match]:
    now = timezone.now()
    base_queryset = _home_match_queryset(now)
    candidates = list(
        base_queryset.order_by("-last_seen_at", "-created_at", "-id")[
            :HOME_MATCH_CANDIDATE_LIMIT
        ]
    )

    important = [match for match in candidates if _league_rating(match) > 0]
    important.sort(
        key=lambda match: (
            -_league_rating(match),
            match.starts_at.timestamp() if match.starts_at else float("inf"),
            match.id,
        )
    )

    if important:
        selected = important[:HOME_MATCHES_LIMIT]
    else:
        selected = list(
            base_queryset.filter(_home_match_has_quick_odds_q())
            .order_by("-last_seen_at", "-created_at", "-id")[:HOME_MATCHES_LIMIT]
        )

    for match in selected:
        match.coupon_odds = _match_winner_odds(match)

    watched_ids = set()
    if request.user.is_authenticated and selected:
        watched_ids = set(
            MatchWatch.objects.filter(
                user=request.user,
                match_id__in=[match.id for match in selected],
            ).values_list("match_id", flat=True)
        )

    for match in selected:
        match.home_can_write_coupon = can_write_coupon
        match.is_watched = match.id in watched_ids
    return selected


@ensure_csrf_cookie
def index(request):
    can_write_coupon = (
        request.user.is_authenticated and request.user.role == User.Role.ANALYST
    )
    ranked_profiles = ranked_expert_profiles(limit=HOME_EXPERTS_LIMIT)

    return render(
        request,
        "front/index.html",
        {
            "latest_predictions": _latest_home_predictions(),
            "best_predictions": _best_home_predictions(request),
            "top_experts": _top_home_experts(ranked_profiles),
            "best_experts": _best_home_experts(request, ranked_profiles),
            "latest_articles": Article.objects.filter(is_published=True).order_by(
                "-created_at", "-id"
            )[:HOME_ARTICLES_LIMIT],
            "recommended_experts": _recommended_experts(request),
            "important_matches": _important_home_matches(request, can_write_coupon),
            "can_write_coupon": can_write_coupon,
        },
    )
