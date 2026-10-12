from django.db.models import Count

from cabinet.vip import plural_ru
from game.models import PredictionCoupon


def apply_prediction_status(queryset, active_status: str):
    if active_status == "pending":
        return queryset.filter(state_status=PredictionCoupon.StateStatus.PENDING)
    if active_status != "all":
        return queryset.filter(state_status=active_status)
    return queryset


def prediction_sport_counts(querysets, *, active_status: str) -> tuple[dict[str, int], int]:
    counts: dict[str, int] = {}
    total = 0
    for queryset in querysets:
        scoped = apply_prediction_status(queryset, active_status)
        total += scoped.values("id").distinct().count()
        rows = (
            scoped.exclude(predictions__match__sport__code__isnull=True)
            .values("predictions__match__sport__code")
            .annotate(total=Count("id", distinct=True))
        )
        for row in rows:
            code = row["predictions__match__sport__code"] or ""
            counts[code] = counts.get(code, 0) + int(row["total"] or 0)
    return counts, total


def build_prediction_head(
    request,
    *,
    title_main: str,
    title_rest: str,
    lede: str,
    total_count: int,
    count_context: str,
    sport_tabs: list[dict],
    status_tabs: list[dict],
    prediction_type_tabs: list[dict] | None,
    active_sort: str,
    sort_options,
    show_content_view_switcher: bool,
) -> dict:
    sort_pairs = list(sort_options)
    sort_labels = dict(sort_pairs)
    sort_keys = [key for key, _label in sort_pairs]
    if active_sort not in sort_keys:
        active_sort = sort_keys[0] if sort_keys else "new"
    next_sort = sort_keys[(sort_keys.index(active_sort) + 1) % len(sort_keys)] if sort_keys else active_sort
    sort_url = _url_with_sort(request, next_sort)
    sports_total = sport_tabs[0]["count"] if sport_tabs else total_count
    return {
        "is_live": False,
        "title_main": title_main,
        "title_rest": title_rest,
        "lede": lede,
        "count": total_count,
        "count_label": f"{plural_ru(total_count, 'прогноз', 'прогноза', 'прогнозов')} {count_context}",
        "with_predictions_label": sort_labels.get(active_sort, "Новые").lower(),
        "sports_total": sports_total,
        "sports_total_label": plural_ru(sports_total, "прогноз", "прогноза", "прогнозов"),
        "all_sports_url": sport_tabs[0]["href"] if sport_tabs else request.path,
        "all_sports_active": not any(tab.get("active") for tab in sport_tabs[1:]),
        "sports": sport_tabs[1:],
        "scopes": [
            {
                "scope": tab["key"],
                "label": tab["label"],
                "url": tab["href"],
                "active": tab.get("active"),
            }
            for tab in status_tabs
            if tab.get("key") != PredictionCoupon.StateStatus.REFUND
        ],
        "prediction_types": prediction_type_tabs or [],
        "sort_label": sort_labels.get(active_sort, "Новые"),
        "sort_url": sort_url,
        "show_content_view_switcher": show_content_view_switcher,
    }


def _url_with_sort(request, value: str) -> str:
    params = request.GET.copy()
    params.pop("page", None)
    if not value or value == "new":
        params.pop("sort", None)
    else:
        params["sort"] = value
    if params.get("status") == "all":
        params.pop("status", None)
    query = params.urlencode()
    return f"{request.path}?{query}" if query else request.path
