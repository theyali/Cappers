from django.shortcuts import render

from cabinet.sport_stats import catalog_sport_stats

from .capper_stats_service import CapperStatsService


def cappers_stats(request):
    service = CapperStatsService(request.user)
    context = service.build_catalog_context()

    analyst_ids = [expert["id"] for expert in context.get("experts", [])]
    sport_stats, sport_options = catalog_sport_stats(analyst_ids)
    for expert in context.get("experts", []):
        expert["sport_stats"] = sport_stats.get(expert["id"], {})

    context["sport_filter_options"] = sport_options
    return render(
        request,
        "front/cappers_stats.html",
        context,
    )
