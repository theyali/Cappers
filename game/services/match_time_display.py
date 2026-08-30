from __future__ import annotations

from datetime import datetime, timedelta

from django.utils import timezone


MONTHS_GENITIVE = (
    "",
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


def format_match_start_label(starts_at: datetime | None, *, now: datetime | None = None) -> str:
    if starts_at is None:
        return "Время не указано"

    if timezone.is_naive(starts_at):
        starts_at = timezone.make_aware(starts_at, timezone.get_current_timezone())
    local_start = timezone.localtime(starts_at)
    local_today = timezone.localdate(now)
    start_date = local_start.date()
    start_time = local_start.strftime("%H:%M")

    if start_date == local_today:
        return f"Сегодня в {start_time}"
    if start_date == local_today + timedelta(days=1):
        return f"Завтра в {start_time}"

    month = MONTHS_GENITIVE[local_start.month]
    if start_date.year != local_today.year:
        return f"{local_start.day} {month} {start_date.year} в {start_time}"
    return f"{local_start.day} {month} в {start_time}"


def format_match_score_or_start_label(match, *, now: datetime | None = None) -> str:
    score = str(getattr(match, "score", "") or "").strip()
    if score:
        return score
    return format_match_start_label(getattr(match, "starts_at", None), now=now)
