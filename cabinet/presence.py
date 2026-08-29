from __future__ import annotations

from datetime import timedelta

from django.core.cache import cache
from django.db import models
from django.db.utils import OperationalError, ProgrammingError
from django.utils import timezone

from .models import User


ONLINE_WINDOW = timedelta(minutes=5)
WRITE_THROTTLE_SECONDS = 60


class UserPresence(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="presence",
        verbose_name="Пользователь",
    )
    last_seen_at = models.DateTimeField("Последняя активность", db_index=True)
    updated_at = models.DateTimeField("Обновлено", auto_now=True)

    class Meta:
        app_label = "cabinet"
        verbose_name = "Онлайн-статус пользователя"
        verbose_name_plural = "Онлайн-статусы пользователей"

    def __str__(self) -> str:
        return f"{self.user} · {self.last_seen_at:%Y-%m-%d %H:%M}"


def touch_user_presence(user, *, now=None, force: bool = False):
    if not getattr(user, "is_authenticated", False) or not getattr(user, "pk", None):
        return None

    moment = now or timezone.now()
    should_write = force
    if not force:
        try:
            should_write = cache.add(
                f"user-presence-touch:{user.pk}",
                "1",
                timeout=WRITE_THROTTLE_SECONDS,
            )
        except Exception:
            should_write = True

    try:
        if not should_write:
            presence = UserPresence.objects.filter(user_id=user.pk).first()
            if presence is not None:
                return presence

        presence, _ = UserPresence.objects.update_or_create(
            user_id=user.pk,
            defaults={"last_seen_at": moment},
        )
        return presence
    except (OperationalError, ProgrammingError):
        # Allows a rolling deploy where web starts before the migration is applied.
        return None


def _local(value):
    if value is None:
        return None
    if timezone.is_aware(value):
        return timezone.localtime(value)
    return value


def _offline_label(last_seen, now) -> str:
    if last_seen is None:
        return "Нет данных о последней активности"

    delta = now - last_seen
    seconds = max(0, int(delta.total_seconds()))

    if seconds < 3600:
        minutes = max(1, seconds // 60)
        return f"Был(а) {minutes} мин назад"
    if seconds < 86400:
        hours = max(1, seconds // 3600)
        return f"Был(а) {hours} ч назад"
    if seconds < 172800:
        return f"Был(а) вчера в {_local(last_seen):%H:%M}"
    if seconds < 604800:
        days = max(2, seconds // 86400)
        return f"Был(а) {days} дн назад"
    return f"Был(а) {_local(last_seen):%d.%m.%Y}"


def presence_payload(user, *, now=None) -> dict:
    moment = now or timezone.now()
    last_seen = None

    try:
        presence = UserPresence.objects.filter(user_id=user.pk).only("last_seen_at").first()
        if presence is not None:
            last_seen = presence.last_seen_at
    except (OperationalError, ProgrammingError):
        presence = None

    if last_seen is None:
        last_seen = getattr(user, "last_login", None)

    is_online = bool(last_seen and moment - last_seen <= ONLINE_WINDOW)
    label = "В сети" if is_online else _offline_label(last_seen, moment)

    return {
        "is_online": is_online,
        "label": label,
        "last_seen_at": last_seen,
    }
