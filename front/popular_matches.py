from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import urlencode

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Case, Count, F, FloatField, Q, Value, When
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast, Coalesce, NullIf, Replace
from django.urls import reverse
from django.utils import timezone

from game.models import Match, PredictionCoupon


POPULAR_MATCHES_SCAN_LIMIT = 500
LEAGUE_RATING_PATHS = (
    ("rating",), ("league_rating",), ("league_rank",), ("rank",), ("priority",), ("popularity",),
    ("league", "rating"), ("data", "rating"),
)

_ODDS_SCALAR_FIELDS = (
    "home_win_bet",
    "x_bet",
    "away_win_bet",
    "goals_over_2_5",
    "goals_under_2_5",
    "fora_1_0",
    "fora_2_0",
    "btts_yes",
    "btts_no",
    "d_1x",
    "d_2x",
    "first_time_home_win_bet",
    "first_time_x_bet",
    "first_time_away_win_bet",
)
_ODDS_JSON_FIELDS = (
    "totals_all",
    "double_chance_all",
    "handicaps_all",
    "btts_all",
    "team_totals_all",
    "first_half_totals_all",
    "first_half_handicaps_all",
    "half_time_full_time_all",
    "exact_score_all",
    "extra_markets",
)


def _safe_number(value) -> float:
    if value in (None, "", False):
        return 0.0
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return 0.0


def _nested_value(data, *path):
    value = data
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def league_rating(match: Match) -> float:
    """Use the configured top-league weight, otherwise provider popularity."""
    league = getattr(match, "league", None)
    if not league:
        return 0.0
    if league.is_top:
        return _safe_number(league.top_order)

    direct_rating = _safe_number(getattr(league, "rating", None))
    if direct_rating > 0:
        return direct_rating

    raw = league.raw_data if isinstance(league.raw_data, dict) else {}
    for path in LEAGUE_RATING_PATHS:
        rating = _safe_number(_nested_value(raw, *path))
        if rating > 0:
            return rating
    return 0.0


def _league_rating_expression():
    # Rank BEFORE limiting the candidate scan: a league rated 20 must not
    # disappear behind 500 earlier games from leagues rated 10.
    ratings = []
    for path in LEAGUE_RATING_PATHS:
        lookup = "league__raw_data__" + "__".join(path)
        text_value = F("league__raw_data")
        for key in path:
            text_value = KeyTextTransform(key, text_value)
        number = Case(
            When(**{lookup + "__regex": r"^[0-9]{1,6}([.,][0-9]{1,6})?$"},
                 then=Cast(Replace(text_value, Value(","), Value(".")), FloatField())),
            default=Value(None), output_field=FloatField(),
        )
        ratings.append(NullIf(number, Value(0.0)))
    return Case(
        When(league__is_top=True, then=Cast(F("league__top_order"), FloatField())),
        default=Coalesce(*ratings, Value(0.0), output_field=FloatField()),
        output_field=FloatField(),
    )


def _contains_coefficient(value) -> bool:
    if isinstance(value, dict):
        return any(_contains_coefficient(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_coefficient(item) for item in value)
    return _safe_number(value) > 1.0


def match_has_odds(match: Match) -> bool:
    try:
        odds = match.odds
    except ObjectDoesNotExist:
        return False

    for field_name in _ODDS_SCALAR_FIELDS:
        if _safe_number(getattr(odds, field_name, None)) > 1.0:
            return True
    for field_name in _ODDS_JSON_FIELDS:
        if _contains_coefficient(getattr(odds, field_name, None)):
            return True
    return False


def _append_unique(target, source, selected_ids: set[int], limit: int) -> None:
    for match in source:
        if len(target) >= limit:
            return
        if match.pk in selected_ids:
            continue
        target.append(match)
        selected_ids.add(match.pk)


def _date_label(starts_at) -> str:
    local_dt = timezone.localtime(starts_at)
    today = timezone.localdate()
    if local_dt.date() == today:
        return "сегодня"
    if local_dt.date() == today + timedelta(days=1):
        return "завтра"
    return local_dt.strftime("%d.%m")


def _serialize_match(match: Match):
    local_start = timezone.localtime(match.starts_at)
    sport = getattr(match, "sport", None)
    return SimpleNamespace(
        id=match.pk,
        url=match.get_absolute_url(),
        starts_at=local_start,
        date_label=_date_label(match.starts_at),
        league_name=match.league_name,
        league_rating=getattr(match, "popular_league_rating", 0.0),
        sport_name=(sport.name_ru or sport.name) if sport else "",
        home_name=match.home_team_name,
        away_name=match.away_team_name,
        home_logo=match.home_team_logo,
        away_logo=match.away_team_logo,
        predictions_count=getattr(match, "published_predictions_count", 0),
    )


def build_popular_matches(limit: int = 5) -> list:
    """Return popular prematches, then prediction-backed and odds-backed fallbacks."""
    try:
        safe_limit = max(1, min(int(limit), 12))
    except (TypeError, ValueError):
        safe_limit = 5

    now = timezone.now()
    candidates = list(
        Match.objects.filter(
            sync_scope=Match.SyncScope.PREMATCH,
            starts_at__gte=now,
        )
        .select_related(
            "sport",
            "league",
            "league__country",
            "home_team__country",
            "away_team__country",
            "odds",
        )
        .annotate(
            popular_league_rating=_league_rating_expression(),
            published_predictions_count=Count(
                "predictions__coupon",
                filter=Q(
                    predictions__coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
                    predictions__coupon__audience=PredictionCoupon.Audience.FREE,
                ),
                distinct=True,
            )
        )
        .order_by("-popular_league_rating", "starts_at", "id")[:POPULAR_MATCHES_SCAN_LIMIT]
    )

    popular = sorted(
        (match for match in candidates if match.popular_league_rating > 0),
        key=lambda match: (
            -match.popular_league_rating,
            match.starts_at,
            match.pk,
        ),
    )
    with_predictions = sorted(
        (match for match in candidates if match.published_predictions_count > 0),
        key=lambda match: (match.starts_at, match.pk),
    )
    with_odds = sorted(
        (match for match in candidates if match_has_odds(match)),
        key=lambda match: (match.starts_at, match.pk),
    )

    selected = []
    selected_ids: set[int] = set()
    _append_unique(selected, popular, selected_ids, safe_limit)
    _append_unique(selected, with_predictions, selected_ids, safe_limit)
    _append_unique(selected, with_odds, selected_ids, safe_limit)

    return [_serialize_match(match) for match in selected]


def build_home_popular_links(best_expert=None):
    """Real home suggestions, sharing match selection and the all-time ranking."""
    links = []
    matches = build_popular_matches(limit=1)
    if matches:
        match = matches[0]
        if match.league_name:
            links.append({"label": match.league_name,
                          "url": reverse("front:search") + "?" + urlencode({"q": match.league_name})})
        links.append({"label": f"{match.home_name} — {match.away_name}", "url": match.url})
    if best_expert is not None:
        user = best_expert.user
        links.append({"label": best_expert.display_name or user.get_full_name() or user.username,
                      "url": reverse("front:expert_profile", kwargs={"username": user.username})})
    links.append({"label": "Экспрессы на сегодня", "url": reverse("front:prediction_expresses")})
    return links
