from django.http import JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string

from .capper_stats_service import CapperStatsService, _best_streaks_for_authors
from .capper_table_service import build_capper_table_context
from .expert_ranking import ranked_expert_profiles


CAPPERS_ROI_PERIODS = {
    "7": {"days": 7, "label": "ROI за 7 дней", "short_label": "7 дней"},
    "30": {"days": 30, "label": "ROI за 30 дней", "short_label": "30 дней"},
    "90": {"days": 90, "label": "ROI за 90 дней", "short_label": "90 дней"},
    "all": {"days": None, "label": "ROI за все время", "short_label": "все время"},
}
DEFAULT_CAPPERS_ROI_PERIOD = "30"
CAPPERS_STATS_GROUPS = {
    "all": "Все эксперты",
    "paid": "Платные прогнозисты",
}


def _roi_period(request):
    key = (request.GET.get("roi_period") or DEFAULT_CAPPERS_ROI_PERIOD).strip().lower()
    if key not in CAPPERS_ROI_PERIODS:
        key = DEFAULT_CAPPERS_ROI_PERIOD
    return key, CAPPERS_ROI_PERIODS[key]


def _stats_group(request) -> str:
    group = (request.GET.get("group") or "all").strip().lower()
    return group if group in CAPPERS_STATS_GROUPS else "all"


def _ranking_cards(
    service: CapperStatsService,
    *,
    period_days,
    period_label: str,
    paid_only: bool = False,
) -> list[dict]:
    profiles = ranked_expert_profiles(period_days=period_days)
    if paid_only:
        profiles = [
            profile
            for profile in profiles
            if profile.paid_predictions_enabled and profile.paid_predictions_price > 0
        ]
    profile_ids = [profile.user_id for profile in profiles]
    best_streaks = _best_streaks_for_authors(profile_ids)
    following_ids = service._following_ids(profile_ids)

    cards = []
    for profile in profiles:
        card = service._serialize_profile(
            profile,
            following_ids=following_ids,
            best_streak=best_streaks.get(profile.user_id, 0),
        )
        card["roi_period_days"] = period_days
        card["roi_period_label"] = period_label
        cards.append(card)
    return cards


def cappers_stats(request):
    service = CapperStatsService(request.user)
    period_key, period = _roi_period(request)
    stats_group = _stats_group(request)
    paid_only = stats_group == "paid"

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        experts = _ranking_cards(
            service,
            period_days=period["days"],
            period_label=period["label"],
            paid_only=paid_only,
        )
        html = render_to_string(
            "front/includes/_cappers_pro_cards.html",
            {"experts": experts},
            request=request,
        )
        return JsonResponse(
            {
                "ok": True,
                "html": html,
                "period": period_key,
                "label": period["label"],
                "experts_count": len(experts),
                "group": stats_group,
            }
        )

    context = service.build_catalog_context(paid_only=paid_only)
    if period_key == DEFAULT_CAPPERS_ROI_PERIOD:
        experts = context["experts"]
        for card in experts:
            card["roi_period_days"] = period["days"]
            card["roi_period_label"] = period["label"]
    else:
        experts = _ranking_cards(
            service,
            period_days=period["days"],
            period_label=period["label"],
            paid_only=paid_only,
        )
        context["experts"] = experts
        context["experts_count"] = len(experts)

    context.update(
        {
            "roi_period_key": period_key,
            "roi_period_days": period["days"],
            "roi_period_label": period["label"],
            "roi_period_options": [
                {"key": key, **item}
                for key, item in CAPPERS_ROI_PERIODS.items()
            ],
            "stats_group": stats_group,
            "stats_group_tabs": [
                {
                    "key": key,
                    "label": label,
                    "url": f"{request.path}?group={key}" if key != "all" else request.path,
                }
                for key, label in CAPPERS_STATS_GROUPS.items()
            ],
        }
    )
    return render(
        request,
        "front/cappers_stats.html",
        context,
    )


def cappers_table(request, group=None, period=None, sport_code=None):
    return render(
        request,
        "front/cappers_table.html",
        build_capper_table_context(
            request,
            group=group,
            period=period,
            sport_code=sport_code,
        ),
    )
