from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re

from django.db.models import Count, Q
from django.http import Http404
from django.urls import reverse

from cabinet.models import AnalystProfile, CapperMonthlyStat, User
from game.models import Sport


GROUP_ALL = "all"
GROUP_VIP = "vip"
GROUP_POPULAR = "popular"
GROUP_PAID = "paid"
VALID_GROUPS = {GROUP_ALL, GROUP_VIP, GROUP_POPULAR, GROUP_PAID}
ALL_SPORTS = "all"
ALL_TIME = "all-time"
PERCENT_STEP = Decimal("0.1")
COEFFICIENT_STEP = Decimal("0.01")
MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
MONTH_NAMES = (
    "",
    "Январь",
    "Февраль",
    "Март",
    "Апрель",
    "Май",
    "Июнь",
    "Июль",
    "Август",
    "Сентябрь",
    "Октябрь",
    "Ноябрь",
    "Декабрь",
)
SPORT_ORDER = {
    "football": 10,
    "tennis": 20,
    "basketball": 30,
    "hockey": 40,
    "esports": 50,
    "table_tennis": 60,
    "table-tennis": 60,
    "tabletennis": 60,
    "volleyball": 70,
    "baseball": 80,
    "rugby": 90,
    "handball": 100,
    "biathlon": 110,
    "formula-1": 120,
    "formula_1": 120,
    "f1": 120,
}


def _percent(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator <= 0:
        return Decimal("0.0")
    return (numerator / denominator * Decimal("100")).quantize(
        PERCENT_STEP,
        rounding=ROUND_HALF_UP,
    )


def _decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _initials(name: str) -> str:
    parts = [part for part in (name or "").split() if part]
    return "".join(part[0] for part in parts[:2]).upper() or "К"


def _month_label(month: date | None) -> str:
    if month is None:
        return "Все время"
    return f"{MONTH_NAMES[month.month]} {month.year}"


def _resolve_group(group: str | None) -> str:
    value = (group or GROUP_ALL).strip().lower()
    if value not in VALID_GROUPS:
        raise Http404("Неизвестный тип рейтинга")
    return value


def _resolve_period(period: str | None, available_months: list[date]) -> tuple[date | None, str]:
    value = (period or ALL_TIME).strip().lower()
    if value == ALL_TIME:
        return None, ALL_TIME
    if not MONTH_RE.match(value):
        raise Http404("Неизвестный период рейтинга")
    year, month = (int(part) for part in value.split("-", 1))
    candidate = date(year, month, 1)
    if candidate not in available_months:
        raise Http404("Для этого месяца нет рейтинга")
    return candidate, value


def _table_url(*, group: str, period: str, sport_code: str) -> str:
    if group == GROUP_ALL and period == ALL_TIME and sport_code == ALL_SPORTS:
        return reverse("front:cappers_table")
    if period == ALL_TIME and sport_code == ALL_SPORTS:
        return reverse("front:cappers_table_group", kwargs={"group": group})
    if sport_code == ALL_SPORTS:
        return reverse(
            "front:cappers_table_period",
            kwargs={"group": group, "period": period},
        )
    return reverse(
        "front:cappers_table_sport",
        kwargs={"group": group, "period": period, "sport_code": sport_code},
    )


def _profile_payload(profile: AnalystProfile) -> dict:
    name = profile.display_name or profile.user.get_full_name() or profile.user.username
    avatar_url = ""
    if profile.avatar:
        avatar_url = profile.avatar.url
    elif profile.user.avatar:
        avatar_url = profile.user.avatar.url
    return {
        "id": profile.user_id,
        "name": name,
        "username": profile.user.username,
        "initials": _initials(name),
        "avatar_url": avatar_url,
        "is_verified": profile.is_verified,
        "is_vip": profile.is_vip,
        "paid_predictions_enabled": bool(
            profile.paid_predictions_enabled and profile.paid_predictions_price > 0
        ),
        "paid_predictions_price": profile.paid_predictions_price,
        "followers": int(getattr(profile, "followers_count", 0) or 0),
    }


def _sport_metrics(payload: dict | None) -> dict | None:
    if not isinstance(payload, dict):
        return None
    bets = int(payload.get("predictions_count") or 0)
    if bets <= 0:
        return None

    wins = int(payload.get("wins_count") or 0)
    losses = int(payload.get("losses_count") or 0)
    refunds = int(payload.get("refunds_count") or 0)
    stake = _decimal(payload.get("allocated_stake"))
    profit = _decimal(payload.get("allocated_profit"))
    flat_units = _decimal(payload.get("flat_units"))
    coefficient_sum = _decimal(payload.get("coefficient_sum"))
    weight = _decimal(payload.get("weight"))
    avg_coefficient = coefficient_sum / weight if weight > 0 else Decimal("0")

    return {
        "bets": bets,
        "wins": wins,
        "losses": losses,
        "refunds": refunds,
        "total_stake": stake,
        "total_profit": profit,
        "flat_units": flat_units,
        "coefficient_sum": coefficient_sum,
        "coefficient_weight": weight,
        "flat_profit_percent": _percent(flat_units, Decimal(bets)),
        "roi": _percent(profit, stake),
        "avg_coefficient": avg_coefficient.quantize(
            COEFFICIENT_STEP,
            rounding=ROUND_HALF_UP,
        ),
        "hit_rate": _percent(Decimal(wins), Decimal(bets)),
    }


def _general_metrics(stat: CapperMonthlyStat) -> dict:
    bets = int(stat.bets_count or 0)
    return {
        "bets": bets,
        "wins": int(stat.wins_count or 0),
        "losses": int(stat.losses_count or 0),
        "refunds": int(stat.refunds_count or 0),
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


def _monthly_rows(
    profiles_by_user: dict[int, AnalystProfile],
    month: date,
    sport_code: str,
) -> list[dict]:
    stats = CapperMonthlyStat.objects.filter(
        month=month,
        analyst_id__in=profiles_by_user.keys(),
    ).order_by()

    rows = []
    for stat in stats:
        profile = profiles_by_user.get(stat.analyst_id)
        if profile is None:
            continue
        metrics = (
            _general_metrics(stat)
            if sport_code == ALL_SPORTS
            else _sport_metrics((stat.sports_data or {}).get(sport_code))
        )
        if not metrics:
            continue
        row = _profile_payload(profile)
        row.update(metrics)
        rows.append(row)
    return rows


def _all_time_rows(
    profiles_by_user: dict[int, AnalystProfile],
    sport_code: str,
) -> list[dict]:
    buckets = defaultdict(
        lambda: {
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
    )

    stats = CapperMonthlyStat.objects.filter(
        analyst_id__in=profiles_by_user.keys(),
    ).order_by()

    for stat in stats:
        bucket = buckets[stat.analyst_id]
        if sport_code == ALL_SPORTS:
            bets = int(stat.bets_count or 0)
            bucket["bets"] += bets
            bucket["wins"] += int(stat.wins_count or 0)
            bucket["losses"] += int(stat.losses_count or 0)
            bucket["refunds"] += int(stat.refunds_count or 0)
            bucket["total_stake"] += _decimal(stat.total_stake)
            bucket["total_profit"] += _decimal(stat.total_profit)
            bucket["flat_units"] += (
                _decimal(stat.flat_profit_percent) / Decimal("100") * Decimal(bets)
            )
            if bets:
                bucket["coefficient_sum"] += _decimal(stat.avg_coefficient) * Decimal(bets)
                bucket["coefficient_weight"] += Decimal(bets)
            continue

        metrics = _sport_metrics((stat.sports_data or {}).get(sport_code))
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

    rows = []
    for analyst_id, bucket in buckets.items():
        profile = profiles_by_user.get(analyst_id)
        bets = int(bucket["bets"] or 0)
        if profile is None or not bets:
            continue

        coefficient_weight = _decimal(bucket["coefficient_weight"])
        avg_coefficient = (
            _decimal(bucket["coefficient_sum"]) / coefficient_weight
            if coefficient_weight > 0
            else Decimal("0")
        )
        row = _profile_payload(profile)
        row.update(
            {
                "bets": bets,
                "wins": bucket["wins"],
                "losses": bucket["losses"],
                "refunds": bucket["refunds"],
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
        )
        rows.append(row)
    return rows


def _sport_catalog(stats_queryset) -> list[dict]:
    snapshots: dict[str, dict] = {}
    for sports_data in stats_queryset.values_list("sports_data", flat=True).iterator(chunk_size=1000):
        if not isinstance(sports_data, dict):
            continue
        for code, payload in sports_data.items():
            if not code or not isinstance(payload, dict):
                continue
            row = snapshots.setdefault(code, {"code": code, "name": "", "image": ""})
            if not row["name"]:
                row["name"] = str(payload.get("name") or "")

    if not snapshots:
        return []

    models_by_code = {
        sport.code: sport
        for sport in Sport.objects.filter(code__in=snapshots.keys()).only(
            "code",
            "name",
            "name_ru",
            "image",
        )
    }
    for code, row in snapshots.items():
        sport = models_by_code.get(code)
        if sport:
            row["name"] = sport.name_ru or sport.name or row["name"] or code.capitalize()
            row["image"] = sport.image or ""
        elif not row["name"]:
            row["name"] = code.replace("_", " ").replace("-", " ").title()
        row["icon_key"] = code.lower().replace("-", "_")

    return sorted(
        snapshots.values(),
        key=lambda row: (SPORT_ORDER.get(row["code"], 999), row["name"].lower()),
    )


def build_capper_table_context(
    request,
    *,
    group: str | None = None,
    period: str | None = None,
    sport_code: str | None = None,
) -> dict:
    base_profiles = (
        AnalystProfile.objects.filter(
            is_public=True,
            user__role=User.Role.ANALYST,
        )
        .select_related("user")
        .annotate(followers_count=Count("user__analyst_followers", distinct=True))
    )

    all_public_ids = list(base_profiles.values_list("user_id", flat=True))
    public_stats = CapperMonthlyStat.objects.filter(analyst_id__in=all_public_ids)
    available_months = list(
        public_stats.order_by("-month").values_list("month", flat=True).distinct()
    )
    sports = _sport_catalog(public_stats)
    available_sport_codes = {item["code"] for item in sports}

    selected_group = _resolve_group(group)
    selected_month, selected_period = _resolve_period(period, available_months)
    selected_sport_code = (sport_code or ALL_SPORTS).strip().lower()
    if selected_sport_code != ALL_SPORTS and selected_sport_code not in available_sport_codes:
        raise Http404("Неизвестный вид спорта")

    search_query = (request.GET.get("q") or "").strip()[:120]
    profiles = base_profiles
    if search_query:
        profiles = profiles.filter(
            Q(display_name__icontains=search_query)
            | Q(user__username__icontains=search_query)
            | Q(user__first_name__icontains=search_query)
            | Q(user__last_name__icontains=search_query)
        )
    if selected_group == GROUP_VIP:
        profiles = profiles.filter(is_vip=True)
    elif selected_group == GROUP_PAID:
        profiles = profiles.filter(
            paid_predictions_enabled=True,
            paid_predictions_price__gt=0,
        )

    profiles_by_user = {profile.user_id: profile for profile in profiles}
    rows = (
        _monthly_rows(profiles_by_user, selected_month, selected_sport_code)
        if selected_month is not None
        else _all_time_rows(profiles_by_user, selected_sport_code)
    )

    if selected_group == GROUP_POPULAR:
        rows.sort(
            key=lambda row: (
                row["followers"],
                row["flat_profit_percent"],
                row["roi"],
                row["bets"],
            ),
            reverse=True,
        )
    else:
        rows.sort(
            key=lambda row: (
                row["flat_profit_percent"],
                row["roi"],
                row["bets"],
                row["followers"],
            ),
            reverse=True,
        )

    group_tabs = [
        {
            "key": GROUP_ALL,
            "label": "Все прогнозисты",
            "url": _table_url(
                group=GROUP_ALL,
                period=selected_period,
                sport_code=selected_sport_code,
            ),
        },
        {
            "key": GROUP_VIP,
            "label": "VIP прогнозисты",
            "url": _table_url(
                group=GROUP_VIP,
                period=selected_period,
                sport_code=selected_sport_code,
            ),
        },
        {
            "key": GROUP_POPULAR,
            "label": "Популярные",
            "url": _table_url(
                group=GROUP_POPULAR,
                period=selected_period,
                sport_code=selected_sport_code,
            ),
        },
        {
            "key": GROUP_PAID,
            "label": "Платные прогнозисты",
            "url": _table_url(
                group=GROUP_PAID,
                period=selected_period,
                sport_code=selected_sport_code,
            ),
        },
    ]

    month_options = [
        {
            "value": ALL_TIME,
            "label": "Все время",
            "url": _table_url(
                group=selected_group,
                period=ALL_TIME,
                sport_code=selected_sport_code,
            ),
        }
    ]
    month_options.extend(
        {
            "value": month.strftime("%Y-%m"),
            "label": _month_label(month),
            "url": _table_url(
                group=selected_group,
                period=month.strftime("%Y-%m"),
                sport_code=selected_sport_code,
            ),
        }
        for month in available_months
    )

    sport_filters = [
        {
            "code": ALL_SPORTS,
            "name": "Общий",
            "image": "",
            "icon_key": "all",
            "url": _table_url(
                group=selected_group,
                period=selected_period,
                sport_code=ALL_SPORTS,
            ),
        }
    ]
    sport_filters.extend(
        {
            **sport,
            "url": _table_url(
                group=selected_group,
                period=selected_period,
                sport_code=sport["code"],
            ),
        }
        for sport in sports
    )

    selected_sport_name = "Все виды спорта"
    if selected_sport_code != ALL_SPORTS:
        selected_sport_name = next(
            (item["name"] for item in sports if item["code"] == selected_sport_code),
            selected_sport_code,
        )

    return {
        "ranking_rows": rows,
        "experts_count": len(rows),
        "selected_group": selected_group,
        "selected_month": selected_month,
        "selected_period": selected_period,
        "selected_month_value": selected_period,
        "selected_month_label": _month_label(selected_month),
        "period_is_all": selected_month is None,
        "selected_sport_code": selected_sport_code,
        "selected_sport_name": selected_sport_name,
        "search_query": search_query,
        "current_table_url": _table_url(
            group=selected_group,
            period=selected_period,
            sport_code=selected_sport_code,
        ),
        "group_tabs": group_tabs,
        "month_options": month_options,
        "sport_filters": sport_filters,
    }
