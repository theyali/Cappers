from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST

from notifications.models import Notification, NotificationSectionState
from notifications.services import refresh_section_state

from .models import DailyTask
from .services.bonus_center import (
    build_bonus_center_context,
    build_bonus_levels_page_context,
    build_bonus_reward_update_context,
    build_bonus_tasks_page_context,
)
from .services.daily_tasks import (
    claim_all_daily_task_rewards,
    claim_daily_task_reward,
    record_daily_task_action,
)


def _bonus_task_notification_items(user) -> list[dict]:
    notifications = list(
        Notification.objects.filter(
            recipient=user,
            kind=Notification.Kind.BONUS_DAILY_TASK,
            show_in_app=True,
            is_read=False,
        ).order_by("-created_at", "-id")[:4]
    )
    return [
        {
            "title": notification.title,
            "message": notification.message,
            "url": notification.url,
            "time_label": timezone.localtime(notification.created_at).strftime("%H:%M"),
        }
        for notification in notifications
    ]


def _mark_bonus_task_notifications_read(user) -> int:
    updated = Notification.objects.filter(
        recipient=user,
        kind=Notification.Kind.BONUS_DAILY_TASK,
        show_in_app=True,
        is_read=False,
    ).update(is_read=True, read_at=timezone.now())
    if updated:
        refresh_section_state(
            user,
            NotificationSectionState.Section.BONUS_TASKS,
        )
    return updated


@login_required
def bonuses(request):
    record_daily_task_action(request.user, DailyTask.TaskType.DAILY_LOGIN)
    context = build_bonus_center_context(request.user, request=request)
    context.update(
        {
            "active_tab": "bonuses",
            "page_class": "cabinet-bonuses-page profile",
        }
    )
    return render(request, "cabinet/bonuses.html", context)


@login_required
def daily_tasks(request):
    record_daily_task_action(request.user, DailyTask.TaskType.DAILY_LOGIN)
    bonus_task_notifications = _bonus_task_notification_items(request.user)
    bonus_task_notifications_read_count = _mark_bonus_task_notifications_read(
        request.user
    )
    context = build_bonus_tasks_page_context(request.user, request=request)
    context.update(
        {
            "active_tab": "bonus_tasks",
            "page_class": "cabinet-bonuses-page cabinet-bonus-tasks-page profile",
            "bonus_task_notifications": bonus_task_notifications,
            "bonus_task_notifications_read_count": bonus_task_notifications_read_count,
        }
    )
    return render(request, "cabinet/bonus_tasks.html", context)


@login_required
def bonus_levels(request):
    context = build_bonus_levels_page_context(request.user, request=request)
    context.update(
        {
            "active_tab": "bonus_levels",
            "page_class": "cabinet-bonuses-page cabinet-bonus-levels-page profile",
        }
    )
    return render(request, "cabinet/bonus_levels.html", context)


@login_required
@require_POST
def daily_task_claim(request, task_id):
    try:
        claim_daily_task_reward(request.user, task_id)
    except ValidationError as exc:
        message = exc.messages[0] if exc.messages else str(exc)
        return JsonResponse(
            {
                "ok": False,
                "error": message,
            },
            status=400,
        )

    return JsonResponse(
        {
            "ok": True,
            **build_bonus_reward_update_context(request.user),
        }
    )


@login_required
@require_POST
def daily_tasks_claim_all(request):
    claim_all_daily_task_rewards(request.user)
    return JsonResponse(
        {
            "ok": True,
            **build_bonus_reward_update_context(request.user),
        }
    )
