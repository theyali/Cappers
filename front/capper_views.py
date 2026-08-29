from django.shortcuts import render

from .capper_stats_service import CapperStatsService
from .capper_table_service import build_capper_table_context


def cappers_stats(request):
    service = CapperStatsService(request.user)
    context = service.build_catalog_context()
    return render(
        request,
        "front/cappers_stats.html",
        context,
    )


def cappers_table(request):
    return render(
        request,
        "front/cappers_table.html",
        build_capper_table_context(request),
    )
