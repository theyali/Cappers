from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .services.bonus_center import build_bonus_center_context


@login_required
def bonuses(request):
    context = build_bonus_center_context(request.user, request=request)
    context.update(
        {
            "active_tab": "bonuses",
            "page_class": "cabinet-bonuses-page",
        }
    )
    return render(request, "cabinet/bonuses.html", context)
