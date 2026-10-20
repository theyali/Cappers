"""Private dialogs: participant-scoped reads and idempotent, rate-limited sends."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from cabinet.models import DirectMessage, User
from cappers.ratelimit import rate_limited
from notifications.models import Notification, NotificationSectionState
from notifications.services import create_notification, refresh_section_state


def dialog_messages(user, peer):
    return DirectMessage.objects.filter(Q(sender=user, recipient=peer) | Q(sender=peer, recipient=user)).select_related("sender")


def send_direct_message(*, sender, recipient, body, client_id):
    if sender.pk == recipient.pk or not recipient.is_active or not sender.is_active:
        raise PermissionDenied
    body = str(body).strip()
    if not body or len(body) > 2000:
        raise ValidationError("Сообщение должно содержать от 1 до 2000 символов.")
    with transaction.atomic():
        list(User.objects.select_for_update(no_key=True).filter(pk__in=[sender.pk, recipient.pk]).order_by("pk"))
        existing = DirectMessage.objects.filter(sender=sender, client_id=client_id).first()
        if existing:
            if existing.recipient_id != recipient.pk or existing.body != body:
                raise ValidationError("Этот запрос уже использован для другого сообщения.")
            return existing
        if rate_limited(f"direct-message:{sender.pk}", limit=20, window=60):
            raise ValidationError("Слишком много сообщений. Повторите через минуту.")
        message = DirectMessage.objects.create(sender=sender, recipient=recipient, body=body, client_id=client_id)
        create_notification(recipient=recipient, actor=sender, kind=Notification.Kind.DIRECT_MESSAGE,
                            title=f"Новое сообщение от @{sender.username}", message="Откройте личный диалог, чтобы прочитать сообщение.",
                            url=reverse("cabinet:dialog", args=[sender.username]), event_key=f"direct-message:{message.pk}")
        return message


def mark_dialog_read(user, peer):
    DirectMessage.objects.filter(sender=peer, recipient=user, read_at__isnull=True).update(read_at=timezone.now())
    Notification.objects.filter(recipient=user, actor=peer, kind=Notification.Kind.DIRECT_MESSAGE, is_read=False).update(is_read=True, read_at=timezone.now())
    refresh_section_state(user, NotificationSectionState.Section.MESSAGES)


def dialog_peers(user):
    return User.objects.exclude(pk=user.pk).filter(
        Q(sent_direct_messages__recipient=user) | Q(received_direct_messages__sender=user)
    ).distinct().order_by("username")
