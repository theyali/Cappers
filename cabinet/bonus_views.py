from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from .models import DailyTask
from .services.bonus_center import build_bonus_center_context
from .services.daily_tasks import record_daily_task_action


@login_required
def bonuses(request):
    record_daily_task_action(request.user, DailyTask.TaskType.DAILY_LOGIN)
    context = build_bonus_center_context(request.user, request=request)
    context.update(
        {
            "active_tab": "bonuses",
            "page_class": "cabinet-bonuses-page",
        }
    )
    return render(request, "cabinet/bonuses.html", context)
