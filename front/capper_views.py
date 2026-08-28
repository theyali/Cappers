from django.shortcuts import render

from .capper_stats_service import CapperStatsService


CAPPER_SORT_OPTIONS = (
    ("rating", "Рейтинг"),
    ("roi", "Лучший ROI"),
    ("followers", "Больше подписчиков"),
    ("active", "Самые активные"),
    ("new", "Новые"),
)
MIN_PUBLICATION_OPTIONS = {"5", "10", "25", "50"}


def _normalized_sort(value: str) -> str:
    valid = {key for key, _ in CAPPER_SORT_OPTIONS}
    return value if value in valid else "rating"


def _filter_catalog_experts(request, experts: list[dict]) -> tuple[list[dict], dict]:
    search_query = request.GET.get("q", "").strip()
    active_sort = _normalized_sort(request.GET.get("sort", "rating"))
    raw_min_predictions = request.GET.get("min_predictions", "").strip()
    min_predictions = raw_min_predictions if raw_min_predictions in MIN_PUBLICATION_OPTIONS else ""
    only_verified = request.GET.get("verified") == "1"
    only_active = request.GET.get("active") == "1"
    positive_roi = request.GET.get("positive_roi") == "1"
    only_following = bool(
        getattr(request.user, "is_authenticated", False)
        and request.GET.get("following") == "1"
    )

    filtered = list(experts)

    if search_query:
        needle = search_query.casefold()
        filtered = [
            expert
            for expert in filtered
            if needle in str(expert.get("name") or "").casefold()
            or needle in str(expert.get("username") or "").casefold()
        ]

    if min_predictions:
        threshold = int(min_predictions)
        filtered = [
            expert
            for expert in filtered
            if int(expert.get("publications") or 0) >= threshold
        ]

    if only_verified:
        filtered = [expert for expert in filtered if expert.get("verified")]
    if only_active:
        filtered = [
            expert
            for expert in filtered
            if int(expert.get("recent_publications") or 0) > 0
        ]
    if positive_roi:
        filtered = [
            expert
            for expert in filtered
            if float(expert.get("roi") or 0) > 0
        ]
    if only_following:
        filtered = [expert for expert in filtered if expert.get("is_following")]

    if active_sort == "roi":
        filtered.sort(
            key=lambda expert: (
                float(expert.get("roi") or 0),
                int(expert.get("settled_in_roi_period") or 0),
                int(expert.get("publications") or 0),
            ),
            reverse=True,
        )
    elif active_sort == "followers":
        filtered.sort(
            key=lambda expert: (
                int(expert.get("followers") or 0),
                float(expert.get("ranking_score") or 0),
                int(expert.get("publications") or 0),
            ),
            reverse=True,
        )
    elif active_sort == "active":
        filtered.sort(
            key=lambda expert: (
                int(expert.get("recent_publications") or 0),
                expert.get("last_publication_at") is not None,
                expert.get("last_publication_at"),
                float(expert.get("ranking_score") or 0),
            ),
            reverse=True,
        )
    elif active_sort == "new":
        filtered.sort(
            key=lambda expert: expert.get("joined_at"),
            reverse=True,
        )

    active_filter_count = sum(
        [
            bool(search_query),
            bool(min_predictions),
            only_verified,
            only_active,
            positive_roi,
            only_following,
        ]
    )

    return filtered, {
        "active_sort": active_sort,
        "catalog_sort_options": CAPPER_SORT_OPTIONS,
        "search_query": search_query,
        "min_predictions": min_predictions,
        "only_verified": only_verified,
        "only_active": only_active,
        "positive_roi": positive_roi,
        "only_following": only_following,
        "active_filter_count": active_filter_count,
        "has_catalog_filters": active_filter_count > 0,
    }


def cappers_stats(request):
    service = CapperStatsService(request.user)
    context = service.build_catalog_context()
    experts, filter_context = _filter_catalog_experts(request, context["experts"])
    context.update(filter_context)
    context["experts"] = experts
    context["filtered_experts_count"] = len(experts)

    return render(
        request,
        "front/cappers_stats.html",
        context,
    )
