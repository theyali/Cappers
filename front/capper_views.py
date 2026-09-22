from django.shortcuts import render

from .capper_table_service import build_capper_table_context


def cappers_table(request, group=None, period=None, sport_code=None):
    context = build_capper_table_context(
        request,
        group=group,
        period=period,
        sport_code=sport_code,
    )
    if request.GET.get("partial") == "ranking":
        return render(request, "front/includes/_cappers_ranking_region.html", context)
    return render(
        request,
        "front/cappers_table.html",
        context,
    )
