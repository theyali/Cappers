from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from cabinet.models import BonusEvent, DailyTask, UserDailyTaskProgress

from .bonus_rewards import grant_bonus_reward
from .streaks import touch_daily_streak


def daily_tasks_for_user(user):
    audiences = [DailyTask.Audience.ALL]
    if user.is_analyst:
        audiences.append(DailyTask.Audience.CAPPER)
    else:
        audiences.append(DailyTask.Audience.READER)

    return DailyTask.objects.filter(
        is_active=True,
        audience__in=audiences,
    ).order_by("order", "id")


def get_today_task_progress(user, now=None):
    progress_date = timezone.localdate(now)
    return list(
        UserDailyTaskProgress.objects.filter(
            user=user,
            progress_date=progress_date,
            task__in=daily_tasks_for_user(user),
        )
        .select_related("task")
        .order_by("task__order", "task_id")
    )


@transaction.atomic
def record_daily_task_action(user, task_type, amount=1, related_obj=None):
    try:
        amount = int(amount)
    except (TypeError, ValueError) as exc:
        raise ValidationError("Прогресс задания должен быть целым числом.") from exc

    if amount <= 0:
        raise ValidationError("Прогресс задания должен быть больше нуля.")
    if task_type not in DailyTask.TaskType.values:
        raise ValidationError("Неизвестный тип ежедневного задания.")

    now = timezone.now()
    progress_date = timezone.localdate(now)
    touch_daily_streak(user, now=now)
    locked_user = user.__class__.objects.select_for_update().get(pk=user.pk)
    tasks = list(
        daily_tasks_for_user(locked_user).filter(task_type=task_type)
    )

    updated_progress = []
    for task in tasks:
        progress, _ = UserDailyTaskProgress.objects.get_or_create(
            user=locked_user,
            task=task,
            progress_date=progress_date,
        )
        progress = UserDailyTaskProgress.objects.select_for_update().get(pk=progress.pk)

        if not progress.is_completed:
            progress.current_value = min(
                task.target_value,
                progress.current_value + amount,
            )
            if progress.current_value >= task.target_value:
                progress.is_completed = True
                progress.completed_at = now

            progress.save(
                update_fields=(
                    "current_value",
                    "is_completed",
                    "completed_at",
                )
            )

        updated_progress.append(progress)

    return updated_progress


@transaction.atomic
def claim_daily_task_reward(user, task_id):
    now = timezone.now()
    progress_date = timezone.localdate(now)
    locked_user = user.__class__.objects.select_for_update().get(pk=user.pk)

    task = daily_tasks_for_user(locked_user).filter(pk=task_id).first()
    if task is None:
        raise ValidationError("Ежедневное задание не найдено.")

    progress = (
        UserDailyTaskProgress.objects.select_for_update()
        .filter(
            user=locked_user,
            task=task,
            progress_date=progress_date,
        )
        .first()
    )
    if progress is None or not progress.is_completed:
        raise ValidationError("Задание ещё не выполнено.")
    if progress.reward_claimed_at is not None:
        return progress

    grant_bonus_reward(
        locked_user,
        xp=task.reward_xp,
        coins=task.reward_coins,
        spins=task.reward_spins,
        event_type=BonusEvent.EventType.DAILY_TASK,
        title=task.title,
        description=task.description or "Награда за ежедневное задание",
        related_obj=progress,
    )

    progress.reward_claimed_at = now
    progress.save(update_fields=("reward_claimed_at",))
    return progress


def _task_reward_label(task) -> str:
    rewards = []
    if task.reward_xp:
        rewards.append(f"+{task.reward_xp} XP")
    if task.reward_coins:
        rewards.append(f"+{task.reward_coins} монет")
    if task.reward_spins:
        rewards.append(f"+{task.reward_spins} попыток")
    return " · ".join(rewards)


def build_daily_tasks_card(user) -> dict:
    tasks = list(daily_tasks_for_user(user))
    progress_by_task_id = {
        progress.task_id: progress
        for progress in get_today_task_progress(user)
    }

    items = []
    completed_count = 0
    claimable_count = 0

    for task in tasks:
        progress = progress_by_task_id.get(task.pk)
        current_value = progress.current_value if progress is not None else 0
        is_completed = bool(progress and progress.is_completed)
        is_claimed = bool(progress and progress.reward_claimed_at)

        if is_completed:
            completed_count += 1

        if is_claimed:
            status = "completed"
            status_label = "Выполнено"
            can_claim = False
        elif is_completed:
            status = "claim"
            status_label = "Получить"
            can_claim = True
            claimable_count += 1
        else:
            status = "in_progress"
            status_label = f"{current_value} из {task.target_value}"
            can_claim = False

        items.append(
            {
                "id": task.pk,
                "title": task.title,
                "description": task.description,
                "current_value": current_value,
                "target_value": task.target_value,
                "is_completed": is_completed,
                "is_claimed": is_claimed,
                "can_claim": can_claim,
                "status": status,
                "status_label": status_label,
                "reward_label": _task_reward_label(task),
            }
        )

    all_claimed = bool(items) and all(item["is_claimed"] for item in items)
    if claimable_count:
        card_status = "claim"
        card_status_label = "Получить"
    elif all_claimed:
        card_status = "completed"
        card_status_label = "Выполнено"
    else:
        card_status = "in_progress"
        card_status_label = ""

    return {
        "title": "Ежедневные задания",
        "completed": completed_count,
        "total": len(items),
        "claimable_count": claimable_count,
        "status": card_status,
        "status_label": card_status_label,
        "progress_slots": [
            {"is_completed": item["is_completed"]}
            for item in items
        ],
        "tasks": items,
        "description": "Выполняйте простые задания и получайте дополнительные бонусы.",
    }
