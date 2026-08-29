from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urlencode

from django.db.models import Count, Q
from django.urls import reverse

from cabinet.models import AnalystProfile, CapperMonthlyStat, User


GROUP_ALL = "all"
GROUP_VIP = "vip"
GROUP_POPULAR = "popular"
VALID_GROUPS = {GROUP_ALL, GROUP_VIP, GROUP_POPULAR}
PERCENT_STEP = Decimal("0.1")
COEFFICIENT_STEP = Decimal("0.01")
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


def _percent(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator <= 0:
        return Decimal("0.0")
    return (numerator / denominator * Decimal("100")).quantize(
        PERCENT_STEP,
        rounding=ROUND_HALF_UP,
    )


def _decimal(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value or 0))


def _initials(name: str) -> str:
    parts = [part for part in (name or "").split() if part]
    return "".join(part[0] for part in parts[:2]).upper() or "К"


def _month_label(month: date | None) -> str:
    if month is None:
        return "Все время"
    return f"{MONTH_NAMES[month.month]} {month.year}"


def _parse_month(value: str, available_months: list[date]) -> date | None:
    if value == "all":
        return None
    if value:
        try:
            year, month = (int(part) for part in value.split("-", 1))
            candidate = date(year, month, 1)
            if candidate in available_months:
                return candidate
        except (TypeError, ValueError):
            pass
    return available_months[0] if available_months else None


def _table_url(*, group: str, month: str, search: str = "") -> str:
    params = {"group": group, "month": month}
    if search:
        params["q"] = search
    return f"{reverse('front:cappers_table')}?{urlencode(params)}"


def _profile_payload(profile: AnalystProfile) -> dict:
    name = profile.display_name or profile.user.get_full_name() or profile.user.username
    avatar_url = profile.avatar.url if profile.avatar else ""
    return {
        "id": profile.user_id,
        "name": name,
        "username": profile.user.username,
        "initials": _initials(name),
        "avatar_url": avatar_url,
        "is_verified": profile.is_verified,
        "is_vip": profile.is_vip,
        "followers": int(getattr(profile, "followers_count", 0) or 0),
    }


def _monthly_rows(profiles_by_user: dict[int, AnalystProfile], month: date) -> list[dict]:
    stats = CapperMonthlyStat.objects.filter(
        month=month,
        analyst_id__in=profiles_by_user.keys(),
    ).order_by()

    rows = []
    for stat in stats:
        profile = profiles_by_user.get(stat.analyst_id)
        if profile is None:
            continue
        row = _profile_payload(profile)
        row.update(
            {
                "bets": stat.bets_count,
                "wins": stat.wins_count,
                "losses": stat.losses_count,
                "refunds": stat.refunds_count,
                "flat_profit_percent": _decimal(stat.flat_profit_percent).quantize(
                    PERCENT_STEP,
                    rounding=ROUND_HALF_UP,
                ),
                "roi": _decimal(stat.roi).quantize(
                    PERCENT_STEP,
                    rounding=ROUND_HALF_UP,
                ),
                "avg_coefficient": _decimal(stat.avg_coefficient).quantize(
                    COEFFICIENT_STEP,
                    rounding=ROUND_HALF_UP,
                ),
                "hit_rate": _decimal(stat.hit_rate).quantize(
                    PERCENT_STEP,
                    rounding=ROUND_HALF_UP,
                ),
            }
        )
        rows.append(row)
    return rows


def _all_time_rows(profiles_by_user: dict[int, AnalystProfile]) -> list[dict]:
    buckets = defaultdict(
        lambda: {
            "bets": 0,
            "wins": 0,
            "losses": 0,
            "refunds": 0,
            "total_stake": Decimal("0"),
            "total_profit": Decimal("0"),
            "flat_units": Decimal("0"),
            "coefficient_weighted": Decimal("0"),
            "coefficient_weight": 0,
        }
    )

    stats = CapperMonthlyStat.objects.filter(
        analyst_id__in=profiles_by_user.keys(),
    ).order_by()

    for stat in stats:
        bucket = buckets[stat.analyst_id]
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
            bucket["coefficient_weighted"] += _decimal(stat.avg_coefficient) * Decimal(bets)
            bucket["coefficient_weight"] += bets

    rows = []
    for analyst_id, bucket in buckets.items():
        profile = profiles_by_user.get(analyst_id)
        if profile is None or not bucket["bets"]:
            continue

        bets_decimal = Decimal(bucket["bets"])
        coefficient_weight = Decimal(bucket["coefficient_weight"] or 0)
        avg_coefficient = (
            bucket["coefficient_weighted"] / coefficient_weight
            if coefficient_weight > 0
            else Decimal("0")
        )

        row = _profile_payload(profile)
        row.update(
            {
                "bets": bucket["bets"],
                "wins": bucket["wins"],
                "losses": bucket["losses"],
                "refunds": bucket["refunds"],
                "flat_profit_percent": _percent(bucket["flat_units"], bets_decimal),
                "roi": _percent(bucket["total_profit"], bucket["total_stake"]),
                "avg_coefficient": avg_coefficient.quantize(
                    COEFFICIENT_STEP,
                    rounding=ROUND_HALF_UP,
                ),
                "hit_rate": _percent(Decimal(bucket["wins"]), bets_decimal),
            }
        )
        rows.append(row)
    return rows


def build_capper_table_context(request) -> dict:
    base_profiles = (
        AnalystProfile.objects.filter(
            is_public=True,
            user__role=User.Role.ANALYST,
        )
        .select_related("user")
        .annotate(followers_count=Count("user__analyst_followers", distinct=True))
    )

    all_public_ids = list(base_profiles.values_list("user_id", flat=True))
    available_months = list(
        CapperMonthlyStat.objects.filter(analyst_id__in=all_public_ids)
        .order_by("-month")
        .values_list("month", flat=True)
        .distinct()
    )

    raw_group = (request.GET.get("group") or GROUP_ALL).strip().lower()
    selected_group = raw_group if raw_group in VALID_GROUPS else GROUP_ALL
    search_query = (request.GET.get("q") or "").strip()[:120]
    selected_month = _parse_month((request.GET.get("month") or "").strip(), available_months)
    selected_month_value = selected_month.strftime("%Y-%m") if selected_month else "all"

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

    profiles_by_user = {profile.user_id: profile for profile in profiles}
    rows = (
        _monthly_rows(profiles_by_user, selected_month)
        if selected_month is not None
        else _all_time_rows(profiles_by_user)
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
                month=selected_month_value,
                search=search_query,
            ),
        },
        {
            "key": GROUP_VIP,
            "label": "VIP прогнозисты",
            "url": _table_url(
                group=GROUP_VIP,
                month=selected_month_value,
                search=search_query,
            ),
        },
        {
            "key": GROUP_POPULAR,
            "label": "Популярные",
            "url": _table_url(
                group=GROUP_POPULAR,
                month=selected_month_value,
                search=search_query,
            ),
        },
    ]

    month_options = [
        {
            "value": "all",
            "label": "Все время",
            "url": _table_url(
                group=selected_group,
                month="all",
                search=search_query,
            ),
        }
    ]
    month_options.extend(
        {
            "value": month.strftime("%Y-%m"),
            "label": _month_label(month),
            "url": _table_url(
                group=selected_group,
                month=month.strftime("%Y-%m"),
                search=search_query,
            ),
        }
        for month in available_months
    )

    return {
        "ranking_rows": rows,
        "experts_count": len(rows),
        "selected_group": selected_group,
        "selected_month": selected_month,
        "selected_month_value": selected_month_value,
        "selected_month_label": _month_label(selected_month),
        "period_is_all": selected_month is None,
        "search_query": search_query,
        "group_tabs": group_tabs,
        "month_options": month_options,
    }
