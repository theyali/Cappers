from django.shortcuts import render

from .capper_stats_service import CapperStatsService


def cappers_stats(request):
    service = CapperStatsService(request.user)
    return render(
        request,
        "front/cappers_stats.html",
        service.build_catalog_context(),
    )
