from cabinet.models import DailyTask


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
