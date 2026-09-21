from __future__ import annotations

from datetime import date
import re

from django.core.cache import cache
from django.http import Http404
from django.urls import reverse

from cabinet.models import AnalystProfile, CapperMonthlyStat, User
from cabinet.presence import presence_payloads
from game.models import Sport

from .expert_ranking import rank_experts, ranking_cache_version


GROUP_ALL = "all"
GROUP_VIP = "vip"
GROUP_POPULAR = "popular"
GROUP_PAID = "paid"
VALID_GROUPS = {GROUP_ALL, GROUP_VIP, GROUP_POPULAR, GROUP_PAID}
ALL_SPORTS = "all"
ALL_TIME = "all-time"
CAPPER_TABLE_CACHE_TIMEOUT = 300
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


def _cache_get(key: str):
    try:
        return cache.get(key)
    except Exception:
        return None


def _cache_set(key: str, value) -> None:
    try:
        cache.set(key, value, timeout=CAPPER_TABLE_CACHE_TIMEOUT)
    except Exception:
        pass


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
    if profile.user.avatar:
        avatar_url = profile.user.avatar.url
    return {
        "id": profile.user_id,
        "name": name,
        "username": profile.user.username,
        "initials": _initials(name),
        "avatar_url": avatar_url,
        "is_verified": profile.is_verified,
        "is_vip": bool(getattr(profile, "is_vip_active", False)),
        "trust_index": profile.trust_index,
        "paid_predictions_enabled": bool(
            profile.paid_predictions_enabled and profile.paid_predictions_price > 0
        ),
        "paid_predictions_price": profile.paid_predictions_price,
        "followers": int(getattr(profile, "followers_count", 0) or 0),
        "_last_login": profile.user.last_login,
    }


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


def _matches_search(row: dict, search_query: str) -> bool:
    if not search_query:
        return True
    needle = search_query.casefold()
    return needle in row["name"].casefold() or needle in row["username"].casefold()


def _ranking_rows(
    *,
    period: str,
    sport_code: str,
    group: str,
) -> list[dict]:
    rows = []
    for entry in rank_experts(
        period=period,
        sport_code=sport_code,
        group=group,
    ):
        profile = entry["profile"]
        row = _profile_payload(profile)
        row.update(entry["metrics"])
        row["rank"] = entry["rank"]
        row["ranking_reason"] = entry["ranking_reason"]
        rows.append(row)
    return rows


def _build_capper_table_base_context(
    *,
    group: str,
    period: str,
    sport_code: str,
) -> dict:
    public_profile_ids = list(
        AnalystProfile.objects.filter(
            is_public=True,
            user__role=User.Role.ANALYST,
        ).values_list("user_id", flat=True)
    )
    public_stats = CapperMonthlyStat.objects.filter(analyst_id__in=public_profile_ids)
    available_months = list(
        public_stats.order_by("-month").values_list("month", flat=True).distinct()
    )
    sports = _sport_catalog(public_stats)
    available_sport_codes = {item["code"] for item in sports}

    selected_month, selected_period = _resolve_period(period, available_months)
    selected_sport_code = sport_code
    if selected_sport_code != ALL_SPORTS and selected_sport_code not in available_sport_codes:
        raise Http404("Неизвестный вид спорта")

    rows = _ranking_rows(
        period=selected_period,
        sport_code=selected_sport_code,
        group=group,
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
                group=group,
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
                group=group,
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
                group=group,
                period=selected_period,
                sport_code=ALL_SPORTS,
            ),
        }
    ]
    sport_filters.extend(
        {
            **sport,
            "url": _table_url(
                group=group,
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
        "selected_group": group,
        "selected_month": selected_month,
        "selected_period": selected_period,
        "selected_month_value": selected_period,
        "selected_month_label": _month_label(selected_month),
        "period_is_all": selected_month is None,
        "selected_sport_code": selected_sport_code,
        "selected_sport_name": selected_sport_name,
        "current_table_url": _table_url(
            group=group,
            period=selected_period,
            sport_code=selected_sport_code,
        ),
        "group_tabs": group_tabs,
        "month_options": month_options,
        "sport_filters": sport_filters,
    }


def build_capper_table_context(
    request,
    *,
    group: str | None = None,
    period: str | None = None,
    sport_code: str | None = None,
) -> dict:
    selected_group = _resolve_group(group)
    requested_period = (period or ALL_TIME).strip().lower()
    requested_sport_code = (sport_code or ALL_SPORTS).strip().lower()
    cache_key = (
        f"capper-table:v{ranking_cache_version()}:"
        f"group={selected_group}:period={requested_period}:sport={requested_sport_code}"
    )
    base_context = _cache_get(cache_key)
    if base_context is None:
        base_context = _build_capper_table_base_context(
            group=selected_group,
            period=requested_period,
            sport_code=requested_sport_code,
        )
        _cache_set(cache_key, base_context)

    search_query = (request.GET.get("q") or "").strip()[:120]
    rows = [
        dict(row)
        for row in base_context["ranking_rows"]
        if _matches_search(row, search_query)
    ]

    fallback_last_seen = {
        row["id"]: row.get("_last_login")
        for row in rows
        if row.get("id")
    }
    presence_by_id = presence_payloads(
        [row["id"] for row in rows],
        fallback_last_seen=fallback_last_seen,
    )
    for row in rows:
        row.pop("_last_login", None)
        presence = presence_by_id.get(
            row["id"],
            {"is_online": False, "label": "Нет данных о последней активности", "last_seen_at": None},
        )
        row["presence"] = presence
        row["is_online"] = presence["is_online"]

    return {
        **base_context,
        "ranking_rows": rows,
        "experts_count": len(rows),
        "search_query": search_query,
    }
