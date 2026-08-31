from __future__ import annotations

import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from cabinet.models import User

from .models import EmailChangeRequest


EMAIL_REQUEST_TTL_MINUTES = 30


class EmailChangeError(ValueError):
    pass


def start_add_email(user: User, new_email: str) -> EmailChangeRequest:
    _ensure_email_available(new_email, user=user)
    flow = EmailChangeRequest.objects.create(
        user=user,
        purpose=EmailChangeRequest.Purpose.ADD,
        current_email=user.email or "",
        new_email=new_email,
        current_confirmed_at=timezone.now(),
        expires_at=_expires_at(),
    )
    _send_new_email_code(flow)
    return flow


def start_change_confirmation(user: User, request) -> EmailChangeRequest:
    if not user.email:
        raise EmailChangeError("Сначала добавьте почту.")

    flow = EmailChangeRequest.objects.create(
        user=user,
        purpose=EmailChangeRequest.Purpose.CHANGE,
        current_email=user.email,
        current_token=secrets.token_urlsafe(32),
        expires_at=_expires_at(),
    )
    url = request.build_absolute_uri(
        reverse("account_email:confirm_change", kwargs={"token": flow.current_token})
    )
    body = render_to_string(
        "account_email/current_email_confirmation.txt",
        {"user": user, "url": url, "expires_minutes": EMAIL_REQUEST_TTL_MINUTES},
    )
    send_mail(
        "Подтверждение смены почты на КапперХаб",
        body,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=False,
    )
    return flow


def confirm_current_email_token(user: User, token: str) -> EmailChangeRequest:
    flow = _active_flow(user).filter(
        purpose=EmailChangeRequest.Purpose.CHANGE,
        current_token=token,
    ).first()
    if flow is None:
        raise EmailChangeError("Ссылка подтверждения недействительна.")
    if flow.is_expired:
        raise EmailChangeError("Срок действия ссылки истек.")
    if (user.email or "").lower() != (flow.current_email or "").lower():
        raise EmailChangeError("Этот запрос смены почты устарел.")
    if flow.current_confirmed_at is None:
        flow.current_confirmed_at = timezone.now()
        flow.save(update_fields=["current_confirmed_at", "updated_at"])
    return flow


def send_change_new_email_code(
    flow: EmailChangeRequest,
    user: User,
    new_email: str,
) -> EmailChangeRequest:
    if flow.user_id != user.pk or flow.completed_at is not None:
        raise EmailChangeError("Запрос смены почты недействителен.")
    if flow.is_expired:
        raise EmailChangeError("Срок действия запроса истек.")
    if flow.purpose != EmailChangeRequest.Purpose.CHANGE or flow.current_confirmed_at is None:
        raise EmailChangeError("Сначала подтвердите текущую почту.")
    _ensure_email_available(new_email, user=user)
    flow.new_email = new_email
    _send_new_email_code(flow)
    return flow


def complete_email_change(user: User, flow_id: int, code: str) -> EmailChangeRequest:
    with transaction.atomic():
        flow = (
            EmailChangeRequest.objects.select_for_update()
            .filter(pk=flow_id, user=user, completed_at__isnull=True)
            .first()
        )
        if flow is None:
            raise EmailChangeError("Запрос подтверждения не найден.")
        if flow.is_expired:
            raise EmailChangeError("Срок действия кода истек.")
        if flow.current_confirmed_at is None:
            raise EmailChangeError("Сначала подтвердите текущую почту.")
        if not flow.new_email or not flow.code_hash:
            raise EmailChangeError("Код для новой почты еще не отправлен.")
        if flow.purpose == EmailChangeRequest.Purpose.ADD and user.email:
            raise EmailChangeError("У аккаунта уже есть почта.")
        if (
            flow.purpose == EmailChangeRequest.Purpose.CHANGE
            and (user.email or "").lower() != (flow.current_email or "").lower()
        ):
            raise EmailChangeError("Этот запрос смены почты устарел.")
        if not check_password(code, flow.code_hash):
            raise EmailChangeError("Неверный код подтверждения.")
        _ensure_email_available(flow.new_email, user=user)

        user.email = flow.new_email
        user.save(update_fields=["email"])
        flow.completed_at = timezone.now()
        flow.save(update_fields=["completed_at", "updated_at"])
        return flow


def _send_new_email_code(flow: EmailChangeRequest) -> str:
    code = f"{secrets.randbelow(1_000_000):06d}"
    flow.code_hash = make_password(code)
    flow.new_code_sent_at = timezone.now()
    flow.expires_at = _expires_at()
    flow.save(
        update_fields=[
            "new_email",
            "code_hash",
            "new_code_sent_at",
            "expires_at",
            "updated_at",
        ]
    )
    body = render_to_string(
        "account_email/new_email_code.txt",
        {
            "user": flow.user,
            "code": code,
            "new_email": flow.new_email,
            "expires_minutes": EMAIL_REQUEST_TTL_MINUTES,
        },
    )
    send_mail(
        "Код подтверждения почты на КапперХаб",
        body,
        settings.DEFAULT_FROM_EMAIL,
        [flow.new_email],
        fail_silently=False,
    )
    return code


def _active_flow(user: User):
    return EmailChangeRequest.objects.filter(user=user, completed_at__isnull=True)


def _ensure_email_available(email: str, *, user: User) -> None:
    if User.objects.filter(email__iexact=email).exclude(pk=user.pk).exists():
        raise EmailChangeError("Пользователь с такой почтой уже существует.")


def _expires_at():
    return timezone.now() + timedelta(minutes=EMAIL_REQUEST_TTL_MINUTES)
