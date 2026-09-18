from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .services.bonus_center import build_bonus_center_context
from .services.streaks import touch_daily_streak


@login_required
def bonuses(request):
    touch_daily_streak(request.user)
    context = build_bonus_center_context(request.user, request=request)
    context.update(
        {
            "active_tab": "bonuses",
            "page_class": "cabinet-bonuses-page",
        }
    )
    return render(request, "cabinet/bonuses.html", context)
