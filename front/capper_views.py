from django.shortcuts import render

from .capper_stats_service import CapperStatsService


def cappers_stats(request):
    service = CapperStatsService(request.user)
    context = service.build_catalog_context()
    return render(
        request,
        "front/cappers_stats.html",
        context,
    )


def cappers_table(request):
    service = CapperStatsService(request.user)
    context = service.build_catalog_context()
    return render(
        request,
        "front/cappers_table.html",
        context,
    )
