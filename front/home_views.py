from decimal import Decimal
from time import perf_counter

from django.conf import settings
from django.db import connection
from django.db.models import (
    Case,
    Count,
    DecimalField,
    F,
    IntegerField,
    Prefetch,
    Q,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from django.shortcuts import render
from django.utils import timezone
from django.utils.formats import date_format
from django.views.decorators.csrf import ensure_csrf_cookie

from achievements.models import UserAchievement
from achievements.services import get_analyst_achievement_definitions
from cabinet.achievements import build_achievement_badges
from cabinet.expert_profile_views import _recommended_experts
from cabinet.models import AnalystProfile, User
from front.expert_ranking import (
    current_month_top_expert_ids,
    expert_leader_badges,
    ranked_expert_profiles,
)
from front.models import Article
from front.prediction_views import _decorate_predictions, _published_queryset
from front.recommendations import personalized_recommended_experts
from front.views import DEMO_EXPERTS, _best_streaks_for_authors, _initials
from game.models import Match, Prediction, PredictionCoupon, PredictionCoverImage
from game.views import _match_winner_odds
from notifications.models import MatchWatch


HOME_PREDICTIONS_LIMIT = 8
HOME_BEST_PREDICTIONS_LIMIT = 10
HOME_ARTICLES_LIMIT = 6
HOME_MATCHES_LIMIT = 9
HOME_EXPERTS_LIMIT = 10
HOME_TOP_EXPERTS_LIMIT = 4
HOME_MATCH_CANDIDATE_LIMIT = 120
HOME_MATCH_DEFER_FIELDS = (
    "raw_data",
    "winning_bet_keys",
    "refund_bet_keys",
    "odds_result_data",
    "provider_predictions",
    "odds__raw_data",
    "odds__extra_markets",
)
HOME_PREDICTION_MATCH_DEFER_FIELDS = (
    "match__raw_data",
    "match__winning_bet_keys",
    "match__refund_bet_keys",
    "match__odds_result_data",
    "match__provider_predictions",
)
HOME_SQL_DEBUG_PARAM = "sql_debug"
HOME_SQL_DEBUG_SLOW_MS = 20
HOME_SQL_DEBUG_TOP_LIMIT = 25


def _sql_fingerprint(sql: str) -> str:
    return " ".join((sql or "").split())


def _print_home_sql_debug(*, queries: list[dict], total_seconds: float) -> None:
    total_ms = total_seconds * 1000
    sql_ms = sum(item["duration_ms"] for item in queries)
    print(
        "\n[home-sql-debug] "
        f"total={total_ms:.1f}ms sql={sql_ms:.1f}ms queries={len(queries)}"
    )

    if not queries:
        print("[home-sql-debug] no sql queries\n")
        return

    fingerprints: dict[str, dict] = {}
    for item in queries:
        key = _sql_fingerprint(item["sql"])
        bucket = fingerprints.setdefault(
            key,
            {
                "count": 0,
                "duration_ms": 0.0,
                "sql": key,
            },
        )
        bucket["count"] += 1
        bucket["duration_ms"] += item["duration_ms"]

    repeated = [
        item for item in fingerprints.values()
        if item["count"] > 1
    ]
    repeated.sort(key=lambda item: item["duration_ms"], reverse=True)
    if repeated:
        print("[home-sql-debug] repeated query fingerprints:")
        for index, item in enumerate(repeated[:10], start=1):
            print(
                f"  R{index:02d}. {item['duration_ms']:.1f}ms "
                f"x{item['count']} {item['sql'][:420]}"
            )

    slow_queries = sorted(
        queries,
        key=lambda item: item["duration_ms"],
        reverse=True,
    )
    print(f"[home-sql-debug] top {min(HOME_SQL_DEBUG_TOP_LIMIT, len(slow_queries))} queries:")
    for index, item in enumerate(slow_queries[:HOME_SQL_DEBUG_TOP_LIMIT], start=1):
        marker = " SLOW" if item["duration_ms"] >= HOME_SQL_DEBUG_SLOW_MS else ""
        print(
            f"  Q{index:02d}. {item['duration_ms']:.1f}ms{marker} "
            f"many={item['many']} sql={_sql_fingerprint(item['sql'])[:700]}"
        )
        if item["params"]:
            print(f"       params={str(item['params'])[:300]}")
    print("[home-sql-debug] end\n")


def _render_home_index(request):
    can_write_coupon = (
        request.user.is_authenticated and request.user.role == User.Role.ANALYST
    )
    ranked_profiles = ranked_expert_profiles(limit=HOME_EXPERTS_LIMIT)
    all_time_profiles = ranked_expert_profiles(period_days=None)
    monthly_top_ids = current_month_top_expert_ids(HOME_TOP_EXPERTS_LIMIT)
    monthly_leader_id = monthly_top_ids[0] if monthly_top_ids else None
    all_time_leader_id = all_time_profiles[0].user_id if all_time_profiles else None
    top_profiles, top_experts_scope = _top_home_profiles(
        all_time_profiles,
        monthly_top_ids,
    )
    main_article, latest_articles = _home_articles()
    recommended_experts = (
        personalized_recommended_experts(request)
        if request.user.is_authenticated
        else []
    )
    if not recommended_experts:
        recommended_experts = _recommended_experts(request)

    return render(
        request,
        "front/index.html",
        {
            "latest_predictions": _latest_home_predictions(),
            "best_predictions": _best_home_predictions(request),
            "top_experts": _top_home_experts(
                top_profiles,
                monthly_leader_id=monthly_leader_id,
                all_time_leader_id=all_time_leader_id,
            ),
            "top_experts_scope": top_experts_scope,
            "top_experts_scope_label": (
                "МЕСЯЦ" if top_experts_scope == "month" else "ВСЁ ВРЕМЯ"
            ),
            "best_experts": _best_home_experts(
                request,
                ranked_profiles,
                monthly_leader_id=monthly_leader_id,
                all_time_leader_id=all_time_leader_id,
            ),
            "main_article": main_article,
            "latest_articles": latest_articles,
            "recommended_experts": recommended_experts,
            "important_matches": _important_home_matches(request, can_write_coupon),
            "can_write_coupon": can_write_coupon,
            "hide_footer": False,
        },
    )


def _render_home_index_with_sql_debug(request):
    queries = []

    def wrapper(execute, sql, params, many, context):
        started_at = perf_counter()
        try:
            return execute(sql, params, many, context)
        finally:
            queries.append(
                {
                    "duration_ms": (perf_counter() - started_at) * 1000,
                    "sql": sql,
                    "params": params,
                    "many": many,
                }
            )

    started_at = perf_counter()
    with connection.execute_wrapper(wrapper):
        response = _render_home_index(request)
    _print_home_sql_debug(
        queries=queries,
        total_seconds=perf_counter() - started_at,
    )
    return response


def _logo_url(primary: str, related) -> str:
    if primary:
        return primary
    if related is not None and getattr(related, "logo_url", ""):
        return related.logo_url
    return ""


def _state_label(prediction: PredictionCoupon) -> tuple[str, str]:
    if prediction.state_status == PredictionCoupon.StateStatus.WIN:
        return "Выигрыш", "win"
    if prediction.state_status == PredictionCoupon.StateStatus.LOSE:
        return "Проигрыш", "lose"
    if prediction.state_status == PredictionCoupon.StateStatus.REFUND:
        return "Возврат", "refund"
    return "Ожидает", "pending"


def _home_cover_pools() -> dict[tuple[str, str, int | None], list[PredictionCoverImage]]:
    pools: dict[tuple[str, str, int | None], list[PredictionCoverImage]] = {}
    covers = PredictionCoverImage.objects.filter(is_active=True).only(
        "id",
        "placement",
        "cover_type",
        "sport_id",
        "image",
    ).order_by("id")
    for cover in covers:
        key = (cover.placement, cover.cover_type, cover.sport_id)
        pools.setdefault(key, []).append(cover)
    return pools


def _home_slider_cover(
    prediction: PredictionCoupon,
    match: Match,
    positions_count: int,
    cover_pools: dict[tuple[str, str, int | None], list[PredictionCoverImage]],
) -> PredictionCoverImage | None:
    is_express = (
        positions_count > 1
        or prediction.coupon_type == PredictionCoupon.CouponType.EXPRESS
    )
    cover_type = (
        PredictionCoverImage.CoverType.EXPRESS
        if is_express
        else PredictionCoverImage.CoverType.SPORT
    )
    sport_id = None if is_express else match.sport_id

    for placement in (
        PredictionCoverImage.Placement.HOME_SLIDER,
        PredictionCoverImage.Placement.GRID,
    ):
        pool = cover_pools.get((placement, cover_type, sport_id), [])
        if pool:
            return pool[prediction.id % len(pool)]

    existing_cover = prediction.cover_image
    if existing_cover and existing_cover.is_active and existing_cover.image:
        return existing_cover
    return None


def _latest_home_predictions() -> list[dict]:
    positions = Prediction.objects.select_related(
        "match__sport",
        "match__league",
        "match__home_team",
        "match__away_team",
    ).defer(*HOME_PREDICTION_MATCH_DEFER_FIELDS).order_by("id")
    queryset = list(
        PredictionCoupon.objects.filter(
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            audience=PredictionCoupon.Audience.FREE,
        )
        .select_related("author", "author__analyst_profile", "cover_image")
        .prefetch_related(
            Prefetch("predictions", queryset=positions, to_attr="home_positions")
        )
        .order_by("-published_at", "-created_at", "-id")[:HOME_PREDICTIONS_LIMIT]
    )
    cover_pools = _home_cover_pools()

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
        starts_date = "Дата не указана"
        starts_time = "—"
        if match.starts_at:
            local_starts_at = timezone.localtime(match.starts_at)
            starts_at = local_starts_at.strftime("%d.%m · %H:%M")
            starts_date = date_format(local_starts_at, "j E")
            starts_time = local_starts_at.strftime("%H:%M")

        count = len(positions_list)
        cover = _home_slider_cover(prediction, match, count, cover_pools)
        cover_url = cover.image.url if cover and cover.image else ""

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
                    match.league.logo_url if match.league and match.league.logo_url else ""
                ),
                "home_name": match.home_team_name or "Хозяева",
                "away_name": match.away_team_name or "Гости",
                "home_logo": _logo_url(match.home_team_logo, match.home_team),
                "away_logo": _logo_url(match.away_team_logo, match.away_team),
                "cover_url": cover_url,
                "score": match.score or "",
                "pick": pick,
                "market": market,
                "coefficient": coefficient.quantize(Decimal("0.01")),
                "confidence": prediction.confidence,
                "positions_count": count,
                "starts_at": starts_at,
                "starts_date": starts_date,
                "starts_time": starts_time,
                "expert": expert_name,
                "expert_username": author.username,
                "expert_initials": _initials(expert_name),
                "expert_avatar_url": (
                    author.avatar.url if author.avatar else ""
                ),
                "expert_verified": bool(profile and profile.is_verified),
                "expert_trust_index": profile.trust_index if profile else Decimal("0.0"),
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
    cards = _decorate_predictions(request, queryset)
    if not cards:
        return cards

    featured = cards[0]
    money_field = DecimalField(max_digits=18, decimal_places=4)
    stats = PredictionCoupon.objects.filter(
        author_id=featured.coupon.author_id,
        published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
    ).aggregate(
        predictions_count=Count("id"),
        wins_count=Count(
            "id",
            filter=Q(state_status=PredictionCoupon.StateStatus.WIN),
        ),
        losses_count=Count(
            "id",
            filter=Q(state_status=PredictionCoupon.StateStatus.LOSE),
        ),
        total_profit=Sum(
            Case(
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
        ),
    )

    wins_count = stats["wins_count"] or 0
    losses_count = stats["losses_count"] or 0
    decided_count = wins_count + losses_count
    featured.expert_predictions_count = stats["predictions_count"] or 0
    featured.expert_hit_rate = (
        Decimal(wins_count) * Decimal("100") / Decimal(decided_count)
        if decided_count
        else Decimal("0")
    )
    featured.expert_profit = stats["total_profit"] or Decimal("0")
    return cards


def _top_home_profiles(all_time_profiles, monthly_top_ids: list[int]) -> tuple[list, str]:
    if monthly_top_ids:
        profiles_by_id = {profile.user_id: profile for profile in all_time_profiles}
        monthly_profiles = [
            profiles_by_id[user_id]
            for user_id in monthly_top_ids
            if user_id in profiles_by_id
        ]
        if monthly_profiles:
            return monthly_profiles, "month"
    return list(all_time_profiles[:HOME_TOP_EXPERTS_LIMIT]), "all_time"


def _home_articles() -> tuple[Article | None, list[Article]]:
    queryset = Article.objects.filter(is_published=True).select_related("category")
    main_article = queryset.filter(is_main=True).order_by("-created_at", "-id").first()
    if main_article is None:
        main_article = queryset.order_by("-created_at", "-id").first()

    latest_articles = queryset.order_by("-created_at", "-id")
    if main_article is not None:
        latest_articles = latest_articles.exclude(pk=main_article.pk)
    return main_article, list(latest_articles[:HOME_ARTICLES_LIMIT])


def _top_home_experts(
    profiles,
    *,
    monthly_leader_id=None,
    all_time_leader_id=None,
) -> list[dict]:
    if not profiles:
        return DEMO_EXPERTS

    experts = []
    for profile in profiles[:HOME_TOP_EXPERTS_LIMIT]:
        name = profile.display_name or profile.user.get_full_name() or profile.user.username
        experts.append(
            {
                "id": profile.user_id,
                "name": name,
                "username": profile.user.username,
                "followers": profile.followers_count,
                "initials": _initials(name),
                "verified": profile.is_verified,
                "avatar_url": profile.user.avatar.url if profile.user.avatar else "",
                "trust_index": profile.trust_index,
                "leader_badges": expert_leader_badges(
                    profile.user_id,
                    monthly_leader_id=monthly_leader_id,
                    all_time_leader_id=all_time_leader_id,
                ),
            }
        )
    return experts


def _best_home_experts(
    request,
    profiles,
    *,
    monthly_leader_id=None,
    all_time_leader_id=None,
) -> list[dict]:
    profiles = list(profiles[:HOME_EXPERTS_LIMIT])
    profile_user_ids = [profile.user_id for profile in profiles]

    best_streaks = _best_streaks_for_authors(profile_user_ids)
    achievement_definitions = list(get_analyst_achievement_definitions())
    achievement_ids = [item.id for item in achievement_definitions]
    awarded_by_user = {}
    if profile_user_ids and achievement_ids:
        awarded_rows = UserAchievement.objects.filter(
            user_id__in=profile_user_ids,
            achievement_id__in=achievement_ids,
        ).values_list("user_id", "achievement_id")
        for user_id, achievement_id in awarded_rows:
            awarded_by_user.setdefault(user_id, set()).add(achievement_id)

    following_ids = set()
    if request.user.is_authenticated:
        following_ids = set(
            request.user.analyst_follows.filter(
                analyst_id__in=profile_user_ids
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
            achievements=achievement_definitions,
            awarded_ids=awarded_by_user.get(profile.user_id, ()),
        )
        experts.append(
            {
                "id": profile.user_id,
                "name": name,
                "username": profile.user.username,
                "initials": _initials(name),
                "avatar_url": profile.user.avatar.url if profile.user.avatar else "",
                "verified": profile.is_verified,
                "trust_index": profile.trust_index,
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
                "leader_badges": expert_leader_badges(
                    profile.user_id,
                    monthly_leader_id=monthly_leader_id,
                    all_time_leader_id=all_time_leader_id,
                ),
                "is_self": (
                    request.user.is_authenticated
                    and request.user.id == profile.user_id
                ),
                "is_following": profile.user_id in following_ids,
            }
        )
    return experts


def _league_rating(match: Match, *, include_match_raw: bool = True) -> int:
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

    for value in values:
        if value in (None, ""):
            continue
        try:
            return int(float(value))
        except (TypeError, ValueError):
            continue

    if not include_match_raw:
        return 0

    match_raw = match.raw_data if isinstance(match.raw_data, dict) else {}
    raw_league = (
        match_raw.get("league")
        if isinstance(match_raw.get("league"), dict)
        else {}
    )
    for value in (
        raw_league.get(key)
        for key in ("rating", "league_rating", "league_rank", "rank")
    ):
        if value in (None, ""):
            continue
        try:
            return int(float(value))
        except (TypeError, ValueError):
            continue
    return 0


def _match_has_quick_odds(match: Match) -> bool:
    try:
        odds = match.odds
    except Match.odds.RelatedObjectDoesNotExist:
        return False
    return any(
        getattr(odds, field, None) is not None
        for field in (
            "home_win_bet",
            "x_bet",
            "away_win_bet",
            "goals_over_2_5",
            "goals_under_2_5",
            "btts_yes",
        )
    )


def _home_match_queryset(now):
    return (
        Match.objects.filter(sync_scope=Match.SyncScope.PREMATCH)
        .filter(Q(starts_at__gte=now) | Q(starts_at__isnull=True))
        .select_related(
            "sport",
            "league__country",
            "home_team__country",
            "away_team__country",
            "odds",
            "metrics",
        )
        .defer(*HOME_MATCH_DEFER_FIELDS)
        .annotate(
            predictions_count=Coalesce(
                F("metrics__predictions_count"),
                Value(0),
                output_field=IntegerField(),
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

    league_ratings = {
        match.id: _league_rating(match, include_match_raw=False)
        for match in candidates
    }
    important = [match for match in candidates if league_ratings.get(match.id, 0) > 0]
    important.sort(
        key=lambda match: (
            -league_ratings.get(match.id, 0),
            match.starts_at.timestamp() if match.starts_at else float("inf"),
            match.id,
        )
    )

    if important:
        selected = important[:HOME_MATCHES_LIMIT]
    else:
        selected = [
            match
            for match in candidates
            if _match_has_quick_odds(match)
        ][:HOME_MATCHES_LIMIT]

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
    if settings.DEBUG and request.GET.get(HOME_SQL_DEBUG_PARAM) == "1":
        return _render_home_index_with_sql_debug(request)
    return _render_home_index(request)
