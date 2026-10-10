from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re

from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, ExpressionWrapper, F, IntegerField, Max, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from cabinet.models import AnalystFollow, AnalystProfile, CapperMonthlyStat, User
from cabinet.vip import annotate_vip_status
from game.models import Prediction, PredictionCoupon
from .models import ExpertRankingEntry, ExpertRankingSnapshot

from .prediction_metrics import ROI_PERIOD_DAYS, annotate_author_roi, roi_period_q


RANKING_HISTORY_PRIOR = 10
RANKING_TRUST_WEIGHT = Decimal("1000")
RANKING_STABILIZED_ROI_CAP = Decimal("25")
RANKING_ACTIVITY_MAX_BONUS = Decimal("5")
RANKING_ACTIVITY_FULL_COUNT = 50
RANKING_CACHE_VERSION_KEY = "expert-ranking:version"
ALL_TIME = "all-time"
ALL_SPORTS = "all"
VALID_GROUPS = {"all", "vip", "paid", "popular"}
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
PERCENT_STEP = Decimal("0.1")
COEFFICIENT_STEP = Decimal("0.01")
SETTLED_EXPERT_STATES = (
    PredictionCoupon.StateStatus.WIN,
    PredictionCoupon.StateStatus.LOSE,
    PredictionCoupon.StateStatus.REFUND,
)


def current_month_start():
    today = timezone.localdate()
    return today.replace(day=1)


def ranking_cache_version() -> int:
    """Return the shared generation used by all ranking-derived caches."""
    try:
        version = cache.get(RANKING_CACHE_VERSION_KEY)
        if version is None:
            cache.add(RANKING_CACHE_VERSION_KEY, 1, timeout=None)
            version = cache.get(RANKING_CACHE_VERSION_KEY)
        return int(version or 1)
    except Exception:
        return 1


def invalidate_expert_ranking_cache() -> None:
    """Invalidate every ranking/table variant without backend-specific wildcard deletes."""
    try:
        if cache.add(RANKING_CACHE_VERSION_KEY, 2, timeout=None):
            return
        cache.incr(RANKING_CACHE_VERSION_KEY)
    except Exception:
        try:
            cache.set(
                RANKING_CACHE_VERSION_KEY,
                max(2, int(timezone.now().timestamp())),
                timeout=None,
            )
        except Exception:
            pass


def _normalize_limit(limit: int | None) -> int | None:
    if limit is None:
        return None
    try:
        return max(0, int(limit))
    except (TypeError, ValueError):
        return 0


def _decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _percent(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator <= 0:
        return Decimal("0.0")
    return (numerator / denominator * Decimal("100")).quantize(
        PERCENT_STEP,
        rounding=ROUND_HALF_UP,
    )


def _ranking_score_values(*, trust_index, roi, settled_count) -> Decimal:
    trust_score = _decimal(trust_index) * RANKING_TRUST_WEIGHT
    settled_count = int(settled_count or 0)
    if settled_count <= 0:
        return trust_score

    stabilized_roi = (
        _decimal(roi)
        * Decimal(settled_count)
        / Decimal(settled_count + RANKING_HISTORY_PRIOR)
    )
    stabilized_roi_score = max(
        -RANKING_STABILIZED_ROI_CAP,
        min(RANKING_STABILIZED_ROI_CAP, stabilized_roi),
    )
    activity_count = min(settled_count, RANKING_ACTIVITY_FULL_COUNT)
    activity_bonus = (
        Decimal(activity_count)
        / Decimal(RANKING_ACTIVITY_FULL_COUNT)
        * RANKING_ACTIVITY_MAX_BONUS
    )
    return trust_score + stabilized_roi_score + activity_bonus


def expert_ranking_score(profile) -> Decimal:
    """Trust-first score used by tests and compatibility callers."""
    return _ranking_score_values(
        trust_index=getattr(profile, "trust_index", 0),
        roi=getattr(profile, "author_roi", 0),
        settled_count=getattr(
            profile,
            "roi_settled_count",
            getattr(profile, "settled_count", 0),
        ),
    )


def _resolve_period(period) -> tuple[date | None, str]:
    if period is None:
        return None, ALL_TIME
    if isinstance(period, date):
        month = period.replace(day=1)
        return month, month.strftime("%Y-%m")

    value = str(period).strip().lower()
    if not value or value == ALL_TIME:
        return None, ALL_TIME
    if not MONTH_RE.match(value):
        raise ValueError(f"Unsupported ranking period: {period}")
    year, month = (int(part) for part in value.split("-", 1))
    resolved = date(year, month, 1)
    return resolved, value


def _resolve_group(group: str | None) -> str:
    value = (group or "all").strip().lower()
    if value not in VALID_GROUPS:
        raise ValueError(f"Unsupported ranking group: {group}")
    return value


def _coupon_tallies(user_ids: list[int], *, period_days: int | None) -> dict[int, dict]:
    """Coupon counters per capper from the coupons table alone.

    Counting coupons, followers and events in one GROUP BY multiplies the rows
    (followers x coupons x events per capper) and made PostgreSQL spill
    gigabytes into temporary files, so each relation is counted on its own.
    """
    recent_cutoff = timezone.now() - timedelta(days=30)
    settled = Q(state_status__in=SETTLED_EXPERT_STATES)
    roi_settled = settled & roi_period_q(days=period_days) if period_days is not None else settled
    rows = (
        PredictionCoupon.objects.filter(
            author_id__in=user_ids,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        )
        .order_by()
        .values("author_id")
        .annotate(
            publications_count=Count("id"),
            settled_count=Count("id", filter=settled),
            roi_settled_count=Count("id", filter=roi_settled),
            wins_count=Count("id", filter=Q(state_status=PredictionCoupon.StateStatus.WIN)),
            losses_count=Count("id", filter=Q(state_status=PredictionCoupon.StateStatus.LOSE)),
            recent_publications_count=Count("id", filter=Q(published_at__gte=recent_cutoff)),
            last_publication_at=Max("published_at"),
        )
    )
    tallies = {row.pop("author_id"): row for row in rows}

    sports = (
        Prediction.objects.filter(
            coupon__author_id__in=user_ids,
            coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        )
        .order_by()
        .values("coupon__author_id")
        .annotate(sports_count=Count("match__sport_id", distinct=True))
    )
    for row in sports:
        tallies.setdefault(row["coupon__author_id"], {})["sports_count"] = row["sports_count"]

    followers = (
        AnalystFollow.objects.filter(analyst_id__in=user_ids)
        .order_by()
        .values("analyst_id")
        .annotate(followers_count=Count("id"))
    )
    for row in followers:
        tallies.setdefault(row["analyst_id"], {})["followers_count"] = row["followers_count"]
    return tallies


TALLY_DEFAULTS = {
    "followers_count": 0,
    "publications_count": 0,
    "settled_count": 0,
    "roi_settled_count": 0,
    "wins_count": 0,
    "losses_count": 0,
    "sports_count": 0,
    "recent_publications_count": 0,
    "last_publication_at": None,
}


def _annotated_public_profiles(
    *,
    period_days: int | None,
) -> list[AnalystProfile]:
    """Load public capper profiles once with all fields used by ranking/cards.

    ``author_roi`` follows the requested display period, while ``ranking_score``
    is always calculated from all-time ROI/history. This keeps the canonical
    all-time place stable when a page merely switches the ROI display period.
    """
    queryset = AnalystProfile.objects.filter(
        is_public=True,
        user__role=User.Role.ANALYST,
    ).select_related("user")
    queryset = annotate_vip_status(
        queryset,
        user_outer_ref="user_id",
        activated_annotation_name="vip_subscription_activated_at",
    )
    queryset = annotate_author_roi(
        queryset,
        author_outer_ref="user_id",
        annotation_name="author_roi",
        period_days=period_days,
    )
    profiles = list(
        annotate_author_roi(
            queryset,
            author_outer_ref="user_id",
            annotation_name="author_roi_all_time",
            period_days=None,
        )
    )
    tallies = _coupon_tallies([profile.user_id for profile in profiles], period_days=period_days)

    for profile in profiles:
        for name, default in TALLY_DEFAULTS.items():
            setattr(profile, name, tallies.get(profile.user_id, {}).get(name, default))
        profile.user.is_vip_active = profile.is_vip_active
        profile.user.vip_ends_at = profile.vip_ends_at
        profile.user.vip_activated_at = profile.vip_subscription_activated_at
        profile.ranking_score = _ranking_score_values(
            trust_index=profile.trust_index,
            roi=profile.author_roi_all_time,
            settled_count=profile.settled_count,
        )
    return profiles


def _filter_group(profiles: list[AnalystProfile], group: str) -> list[AnalystProfile]:
    if group == "vip":
        return [
            profile
            for profile in profiles
            if bool(getattr(profile, "is_vip_active", False))
        ]
    if group == "paid":
        return [
            profile
            for profile in profiles
            if profile.paid_predictions_enabled and profile.paid_predictions_price > 0
        ]
    if group == "popular":
        return [
            profile
            for profile in profiles
            if int(getattr(profile, "followers_count", 0) or 0) > 0
        ]
    return profiles


def _empty_bucket() -> dict:
    return {
        "bets": 0,
        "wins": 0,
        "losses": 0,
        "refunds": 0,
        "total_stake": Decimal("0"),
        "total_profit": Decimal("0"),
        "flat_units": Decimal("0"),
        "coefficient_sum": Decimal("0"),
        "coefficient_weight": Decimal("0"),
    }


def _sport_payload_metrics(payload: dict | None) -> dict | None:
    if not isinstance(payload, dict):
        return None
    bets = int(payload.get("predictions_count") or 0)
    if bets <= 0:
        return None

    wins = int(payload.get("wins_count") or 0)
    losses = int(payload.get("losses_count") or 0)
    refunds = int(payload.get("refunds_count") or 0)
    total_stake = _decimal(payload.get("allocated_stake"))
    total_profit = _decimal(payload.get("allocated_profit"))
    flat_units = _decimal(payload.get("flat_units"))
    coefficient_sum = _decimal(payload.get("coefficient_sum"))
    coefficient_weight = _decimal(payload.get("weight"))
    avg_coefficient = (
        coefficient_sum / coefficient_weight
        if coefficient_weight > 0
        else Decimal("0")
    )
    return {
        "bets": bets,
        "wins": wins,
        "losses": losses,
        "refunds": refunds,
        "total_stake": total_stake,
        "total_profit": total_profit,
        "flat_profit_percent": _percent(flat_units, Decimal(bets)),
        "roi": _percent(total_profit, total_stake),
        "avg_coefficient": avg_coefficient.quantize(
            COEFFICIENT_STEP,
            rounding=ROUND_HALF_UP,
        ),
        "hit_rate": _percent(Decimal(wins), Decimal(bets)),
        "flat_units": flat_units,
        "coefficient_sum": coefficient_sum,
        "coefficient_weight": coefficient_weight,
    }


def _general_month_metrics(stat: CapperMonthlyStat) -> dict | None:
    bets = int(stat.bets_count or 0)
    if bets <= 0:
        return None
    return {
        "bets": bets,
        "wins": int(stat.wins_count or 0),
        "losses": int(stat.losses_count or 0),
        "refunds": int(stat.refunds_count or 0),
        "total_stake": _decimal(stat.total_stake),
        "total_profit": _decimal(stat.total_profit),
        "flat_profit_percent": _decimal(stat.flat_profit_percent).quantize(
            PERCENT_STEP,
            rounding=ROUND_HALF_UP,
        ),
        "roi": _decimal(stat.roi).quantize(PERCENT_STEP, rounding=ROUND_HALF_UP),
        "avg_coefficient": _decimal(stat.avg_coefficient).quantize(
            COEFFICIENT_STEP,
            rounding=ROUND_HALF_UP,
        ),
        "hit_rate": _decimal(stat.hit_rate).quantize(
            PERCENT_STEP,
            rounding=ROUND_HALF_UP,
        ),
    }


def _monthly_metrics_map(
    profile_ids: list[int],
    *,
    month: date,
    sport_code: str,
) -> dict[int, dict]:
    result = {}
    stats = CapperMonthlyStat.objects.filter(
        month=month,
        analyst_id__in=profile_ids,
    ).order_by()
    for stat in stats:
        metrics = (
            _general_month_metrics(stat)
            if sport_code == ALL_SPORTS
            else _sport_payload_metrics((stat.sports_data or {}).get(sport_code))
        )
        if metrics and int(metrics.get("bets") or 0) > 0:
            result[stat.analyst_id] = metrics
    return result


def _all_time_metrics_map(
    profile_ids: list[int],
    *,
    sport_code: str,
) -> dict[int, dict]:
    buckets: dict[int, dict] = {}
    stats = CapperMonthlyStat.objects.filter(analyst_id__in=profile_ids).order_by()
    for stat in stats:
        bucket = buckets.setdefault(stat.analyst_id, _empty_bucket())
        if sport_code == ALL_SPORTS:
            bets = int(stat.bets_count or 0)
            if bets <= 0:
                continue
            bucket["bets"] += bets
            bucket["wins"] += int(stat.wins_count or 0)
            bucket["losses"] += int(stat.losses_count or 0)
            bucket["refunds"] += int(stat.refunds_count or 0)
            bucket["total_stake"] += _decimal(stat.total_stake)
            bucket["total_profit"] += _decimal(stat.total_profit)
            bucket["flat_units"] += (
                _decimal(stat.flat_profit_percent) / Decimal("100") * Decimal(bets)
            )
            bucket["coefficient_sum"] += _decimal(stat.avg_coefficient) * Decimal(bets)
            bucket["coefficient_weight"] += Decimal(bets)
            continue

        metrics = _sport_payload_metrics((stat.sports_data or {}).get(sport_code))
        if not metrics:
            continue
        bucket["bets"] += metrics["bets"]
        bucket["wins"] += metrics["wins"]
        bucket["losses"] += metrics["losses"]
        bucket["refunds"] += metrics["refunds"]
        bucket["total_stake"] += metrics["total_stake"]
        bucket["total_profit"] += metrics["total_profit"]
        bucket["flat_units"] += metrics["flat_units"]
        bucket["coefficient_sum"] += metrics["coefficient_sum"]
        bucket["coefficient_weight"] += metrics["coefficient_weight"]

    result = {}
    for analyst_id, bucket in buckets.items():
        bets = int(bucket["bets"] or 0)
        if bets <= 0:
            continue
        coefficient_weight = _decimal(bucket["coefficient_weight"])
        avg_coefficient = (
            _decimal(bucket["coefficient_sum"]) / coefficient_weight
            if coefficient_weight > 0
            else Decimal("0")
        )
        result[analyst_id] = {
            "bets": bets,
            "wins": int(bucket["wins"] or 0),
            "losses": int(bucket["losses"] or 0),
            "refunds": int(bucket["refunds"] or 0),
            "total_stake": _decimal(bucket["total_stake"]),
            "total_profit": _decimal(bucket["total_profit"]),
            "flat_profit_percent": _percent(
                _decimal(bucket["flat_units"]),
                Decimal(bets),
            ),
            "roi": _percent(
                _decimal(bucket["total_profit"]),
                _decimal(bucket["total_stake"]),
            ),
            "avg_coefficient": avg_coefficient.quantize(
                COEFFICIENT_STEP,
                rounding=ROUND_HALF_UP,
            ),
            "hit_rate": _percent(Decimal(bucket["wins"]), Decimal(bets)),
        }
    return result


def _all_time_entries(
    *,
    sport_code: str,
    group: str,
    roi_period_days: int | None,
) -> list[dict]:
    profiles = _filter_group(
        _annotated_public_profiles(period_days=roi_period_days),
        group,
    )
    profile_ids = [profile.user_id for profile in profiles]
    metrics_map = _all_time_metrics_map(profile_ids, sport_code=sport_code)

    if sport_code != ALL_SPORTS:
        profiles = [profile for profile in profiles if profile.user_id in metrics_map]

    profiles.sort(key=lambda profile: profile.user.username.lower())
    profiles.sort(
        key=lambda profile: (
            profile.ranking_score,
            profile.settled_count,
            profile.followers_count,
            profile.publications_count,
        ),
        reverse=True,
    )

    entries = []
    for profile in profiles:
        metrics = metrics_map.get(profile.user_id) or {
            "bets": int(getattr(profile, "publications_count", 0) or 0),
            "wins": int(getattr(profile, "wins_count", 0) or 0),
            "losses": int(getattr(profile, "losses_count", 0) or 0),
            "refunds": 0,
            "total_stake": Decimal("0"),
            "total_profit": Decimal("0"),
            "flat_profit_percent": Decimal("0"),
            "roi": _decimal(getattr(profile, "author_roi_all_time", 0)),
            "avg_coefficient": Decimal("0"),
            "hit_rate": Decimal("0"),
        }
        entries.append(
            {
                "profile": profile,
                "metrics": metrics,
                "trust_index": profile.trust_index,
                "ranking_reason": "Общий рейтинг по индексу доверия",
            }
        )
    return entries


def _month_entries(
    *,
    month: date,
    sport_code: str,
    group: str,
) -> list[dict]:
    profiles = _filter_group(
        _annotated_public_profiles(period_days=None),
        group,
    )
    profile_ids = [profile.user_id for profile in profiles]
    metrics_map = _monthly_metrics_map(
        profile_ids,
        month=month,
        sport_code=sport_code,
    )
    profiles = [profile for profile in profiles if profile.user_id in metrics_map]

    profiles.sort(
        key=lambda profile: (
            -_decimal(metrics_map[profile.user_id].get("roi")),
            -_decimal(metrics_map[profile.user_id].get("flat_profit_percent")),
            -int(metrics_map[profile.user_id].get("wins") or 0),
            -_decimal(metrics_map[profile.user_id].get("total_profit")),
            -int(metrics_map[profile.user_id].get("bets") or 0),
            -_decimal(profile.trust_index),
            -int(getattr(profile, "followers_count", 0) or 0),
            profile.user.username.lower(),
            profile.user_id,
        )
    )

    return [
        {
            "profile": profile,
            "metrics": metrics_map[profile.user_id],
            "trust_index": profile.trust_index,
            "ranking_reason": (
                f"Рейтинг за {month:%Y-%m} по месячным результатам; "
                "индекс доверия — дополнительный фактор"
            ),
        }
        for profile in profiles
    ]


def _json_ready(value):
    if isinstance(value, Decimal):
        return {"__decimal__": str(value)}
    if isinstance(value, dict):
        return {key: _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    return value


def _json_restore(value):
    if isinstance(value, dict):
        if set(value.keys()) == {"__decimal__"}:
            return _decimal(value["__decimal__"])
        return {key: _json_restore(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_restore(item) for item in value]
    return value


def _snapshot_entries(
    *,
    period: str,
    sport_code: str,
    group: str,
    roi_period_days: int | None,
) -> list[dict]:
    queryset = (
        ExpertRankingEntry.objects.filter(
            snapshot__period=period,
            snapshot__sport_code=sport_code,
            snapshot__group=group,
            snapshot__roi_period_days=roi_period_days,
        )
        .select_related("analyst", "analyst__analyst_profile")
        .order_by("rank")
    )
    result = []
    for entry in queryset:
        try:
            profile = entry.analyst.analyst_profile
        except AnalystProfile.DoesNotExist:
            continue

        profile.rank = entry.rank
        profile.ranking_metrics = _json_restore(entry.metrics or {})
        profile.ranking_reason = entry.ranking_reason
        profile.author_roi = entry.author_roi
        profile.author_roi_all_time = entry.author_roi_all_time
        profile.ranking_score = entry.ranking_score
        profile.settled_count = entry.settled_count
        profile.roi_settled_count = entry.roi_settled_count
        profile.followers_count = entry.followers_count
        profile.publications_count = entry.publications_count
        profile.wins_count = entry.wins_count
        profile.losses_count = entry.losses_count
        profile.sports_count = entry.sports_count
        profile.recent_publications_count = entry.recent_publications_count
        profile.last_publication_at = entry.last_publication_at
        profile.is_vip_active = entry.is_vip_active
        profile.vip_ends_at = entry.vip_ends_at
        profile.vip_subscription_activated_at = entry.vip_subscription_activated_at
        profile.user.is_vip_active = entry.is_vip_active
        profile.user.vip_ends_at = entry.vip_ends_at
        profile.user.vip_activated_at = entry.vip_subscription_activated_at

        result.append(
            {
                "profile": profile,
                "metrics": profile.ranking_metrics,
                "trust_index": entry.trust_index,
                "ranking_reason": entry.ranking_reason,
                "rank": entry.rank,
                "period": period,
                "sport_code": sport_code,
                "group": group,
            }
        )
    return result


def _entries_for_build(
    *,
    selected_month: date | None,
    selected_period: str,
    selected_sport: str,
    selected_group: str,
    roi_period_days: int | None,
) -> list[dict]:
    if selected_month is None:
        return _all_time_entries(
            sport_code=selected_sport,
            group=selected_group,
            roi_period_days=roi_period_days,
        )
    return _month_entries(
        month=selected_month,
        sport_code=selected_sport,
        group=selected_group,
    )


def rebuild_expert_ranking_snapshot(
    *,
    period=None,
    sport_code: str = ALL_SPORTS,
    group: str = "all",
    roi_period_days: int | None = None,
) -> ExpertRankingSnapshot:
    selected_month, selected_period = _resolve_period(period)
    selected_group = _resolve_group(group)
    selected_sport = (sport_code or ALL_SPORTS).strip().lower()
    entries = _entries_for_build(
        selected_month=selected_month,
        selected_period=selected_period,
        selected_sport=selected_sport,
        selected_group=selected_group,
        roi_period_days=roi_period_days,
    )

    with transaction.atomic():
        snapshot, _ = ExpertRankingSnapshot.objects.select_for_update().get_or_create(
            period=selected_period,
            sport_code=selected_sport,
            group=selected_group,
            roi_period_days=roi_period_days,
        )
        snapshot.entries.all().delete()
        rows = []
        for rank, entry in enumerate(entries, start=1):
            profile = entry["profile"]
            profile.rank = rank
            profile.ranking_metrics = entry["metrics"]
            profile.ranking_reason = entry["ranking_reason"]
            rows.append(
                ExpertRankingEntry(
                    snapshot=snapshot,
                    analyst_id=profile.user_id,
                    rank=rank,
                    metrics=_json_ready(entry["metrics"]),
                    ranking_reason=entry["ranking_reason"],
                    trust_index=_decimal(profile.trust_index),
                    ranking_score=_decimal(getattr(profile, "ranking_score", 0)),
                    author_roi=_decimal(getattr(profile, "author_roi", 0)),
                    author_roi_all_time=_decimal(
                        getattr(profile, "author_roi_all_time", 0)
                    ),
                    settled_count=int(getattr(profile, "settled_count", 0) or 0),
                    roi_settled_count=int(
                        getattr(profile, "roi_settled_count", 0) or 0
                    ),
                    followers_count=int(getattr(profile, "followers_count", 0) or 0),
                    publications_count=int(
                        getattr(profile, "publications_count", 0) or 0
                    ),
                    wins_count=int(getattr(profile, "wins_count", 0) or 0),
                    losses_count=int(getattr(profile, "losses_count", 0) or 0),
                    sports_count=int(getattr(profile, "sports_count", 0) or 0),
                    recent_publications_count=int(
                        getattr(profile, "recent_publications_count", 0) or 0
                    ),
                    last_publication_at=getattr(profile, "last_publication_at", None),
                    is_vip_active=bool(getattr(profile, "is_vip_active", False)),
                    vip_ends_at=getattr(profile, "vip_ends_at", None),
                    vip_subscription_activated_at=getattr(
                        profile,
                        "vip_subscription_activated_at",
                        None,
                    ),
                )
            )
        ExpertRankingEntry.objects.bulk_create(rows, batch_size=500)
        snapshot.entries_count = len(rows)
        snapshot.save(update_fields=("entries_count", "built_at"))
    return snapshot


def refresh_core_expert_rankings(*, periods: list[str] | None = None) -> None:
    target_periods = [ALL_TIME, current_month_start().strftime("%Y-%m")]
    if periods:
        target_periods.extend(periods)

    seen = set()
    for period in target_periods:
        if period in seen:
            continue
        seen.add(period)
        rebuild_expert_ranking_snapshot(
            period=period,
            sport_code=ALL_SPORTS,
            group="all",
            roi_period_days=None,
        )

    rebuild_expert_ranking_snapshot(
        period=ALL_TIME,
        sport_code=ALL_SPORTS,
        group="all",
        roi_period_days=ROI_PERIOD_DAYS,
    )
    invalidate_expert_ranking_cache()


def rank_experts(
    *,
    period=None,
    sport_code: str = ALL_SPORTS,
    group: str = "all",
    limit: int | None = None,
) -> list[dict]:
    """Single source of truth for capper ranking order and places.

    ``period=None``/``all-time`` uses the trust-first all-time ranking.
    ``period=YYYY-MM`` uses only activity and results from that calendar month.
    Sport and group narrow the same canonical order; callers must not re-sort it.
    """
    _selected_month, selected_period = _resolve_period(period)
    selected_group = _resolve_group(group)
    selected_sport = (sport_code or ALL_SPORTS).strip().lower()
    safe_limit = _normalize_limit(limit)
    entries = _snapshot_entries(
        period=selected_period,
        sport_code=selected_sport,
        group=selected_group,
        roi_period_days=None,
    )
    return entries if safe_limit is None else entries[:safe_limit]


def ranked_expert_profiles(
    *,
    limit: int | None = None,
    period_days: int | None = ROI_PERIOD_DAYS,
) -> list[AnalystProfile]:
    """Compatibility layer over the same canonical all-time ranking.

    ``period_days`` changes ``profile.author_roi`` for display only. It no longer
    changes the order, because ``ranking_score`` is always based on all-time
    trust/ROI/history in ``_annotated_public_profiles``.
    """
    safe_limit = _normalize_limit(limit)
    if period_days is None:
        return [
            entry["profile"]
            for entry in rank_experts(
                period=ALL_TIME,
                sport_code=ALL_SPORTS,
                group="all",
                limit=safe_limit,
            )
        ]

    entries = _snapshot_entries(
        period=ALL_TIME,
        sport_code=ALL_SPORTS,
        group="all",
        roi_period_days=period_days,
    )
    profiles = [entry["profile"] for entry in entries]
    return profiles if safe_limit is None else profiles[:safe_limit]


def recommended_experts_for_user(
    user,
    limit: int | None = 6,
) -> list[AnalystProfile]:
    """Return public cappers whose published predictions match user preferences."""
    if not getattr(user, "is_authenticated", False):
        return []

    safe_limit = _normalize_limit(limit)
    if safe_limit == 0:
        return []

    sport_ids = list(
        user.sport_preferences.values_list("sport_id", flat=True)
    )
    league_ids = list(
        user.league_preferences.values_list("league_id", flat=True)
    )
    if not sport_ids and not league_ids:
        return []

    def matching_events(**match_filter):
        # A counting subquery per capper: filtering events in WHERE keeps the scan on the index
        # instead of a COUNT(DISTINCT) over every event of every capper.
        events = (
            Prediction.objects.filter(
                coupon__author_id=OuterRef("user_id"),
                coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
                **match_filter,
            )
            .order_by()
            .values("coupon__author_id")
            .annotate(total=Count("id"))
            .values("total")[:1]
        )
        return Coalesce(Subquery(events, output_field=IntegerField()), Value(0))

    annotations = {
        "preference_sport_matches": (
            matching_events(match__sport_id__in=sport_ids)
            if sport_ids
            else Value(0, output_field=IntegerField())
        ),
        "preference_league_matches": (
            matching_events(match__league_id__in=league_ids)
            if league_ids
            else Value(0, output_field=IntegerField())
        ),
    }

    queryset = (
        AnalystProfile.objects.filter(
            is_public=True,
            user__role=User.Role.ANALYST,
        )
        .exclude(user_id=user.pk)
        .select_related("user")
        .annotate(**annotations)
        .annotate(
            preference_match_score=ExpressionWrapper(
                F("preference_league_matches") * Value(2)
                + F("preference_sport_matches"),
                output_field=IntegerField(),
            )
        )
        .filter(preference_match_score__gt=0)
    )
    queryset = annotate_author_roi(
        queryset,
        author_outer_ref="user_id",
        annotation_name="author_roi",
        period_days=None,
    ).order_by(
        "-preference_match_score",
        "-trust_index",
        "-is_verified",
        "-author_roi",
        "user_id",
    )

    if safe_limit is None:
        return list(queryset)
    return list(queryset[:safe_limit])


def current_month_top_expert_ids(limit: int = 1) -> list[int]:
    month = current_month_start().strftime("%Y-%m")
    return [
        entry["profile"].user_id
        for entry in rank_experts(period=month, limit=limit)
    ]


def expert_leader_badges(
    user_id,
    *,
    monthly_leader_id=None,
    all_time_leader_id=None,
) -> list[dict]:
    badges = []
    if user_id and user_id == all_time_leader_id:
        badges.append({"kind": "all-time", "label": "Лучший аналитик за все время"})
    if user_id and user_id == monthly_leader_id:
        badges.append({"kind": "month", "label": "Лучший прогнозист месяца"})
    return badges
