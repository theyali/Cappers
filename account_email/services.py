from __future__ import annotations

import hashlib
import secrets
from binascii import Error as BinasciiError
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from cabinet.models import User

from .models import EmailChangeRequest, PasswordResetRequest


EMAIL_REQUEST_TTL_MINUTES = 30
PASSWORD_RESET_TTL_MINUTES = 30


class EmailChangeError(ValueError):
    pass


class PasswordResetError(ValueError):
    pass


def send_account_email(*, subject: str, template_name: str, to_email: str, context: dict) -> None:
    body = render_to_string(template_name, context)
    send_mail(
        subject,
        body,
        settings.DEFAULT_FROM_EMAIL,
        [to_email],
        fail_silently=False,
    )


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
    send_account_email(
        subject="Подтверждение смены почты на КапперХаб",
        template_name="account_email/current_email_confirmation.txt",
        to_email=user.email,
        context={"user": user, "url": url, "expires_minutes": EMAIL_REQUEST_TTL_MINUTES},
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


def start_password_reset(user: User, *, request) -> PasswordResetRequest:
    now = timezone.now()
    secret = secrets.token_urlsafe(32)

    with transaction.atomic():
        PasswordResetRequest.objects.filter(
            user=user,
            revoked_at__isnull=True,
            completed_at__isnull=True,
        ).update(revoked_at=now, updated_at=now)

        flow = PasswordResetRequest.objects.create(
            user=user,
            token_hash=make_password(secret),
            password_fingerprint=_password_fingerprint(user),
            expires_at=now + timedelta(minutes=PASSWORD_RESET_TTL_MINUTES),
        )

    uidb64 = urlsafe_base64_encode(force_bytes(user.pk))
    token = f"{flow.pk}-{secret}"
    reset_url = request.build_absolute_uri(
        reverse(
            "cabinet:password_reset_confirm",
            kwargs={"uidb64": uidb64, "token": token},
        )
    )

    try:
        send_account_email(
            subject="Сброс пароля на КапперХаб",
            template_name="account_email/password_reset_email.txt",
            to_email=user.email,
            context={
                "user": user,
                "reset_url": reset_url,
                "expires_minutes": PASSWORD_RESET_TTL_MINUTES,
            },
        )
    except Exception:
        flow.revoked_at = timezone.now()
        flow.save(update_fields=["revoked_at", "updated_at"])
        raise

    return flow


def consume_password_reset_link(uidb64: str, token: str) -> PasswordResetRequest:
    try:
        user_id = int(force_str(urlsafe_base64_decode(uidb64)))
    except (BinasciiError, TypeError, ValueError, OverflowError, UnicodeDecodeError):
        raise PasswordResetError("Ссылка недействительна или уже использована.") from None

    flow_id_raw, separator, secret = token.partition("-")
    if not separator or not flow_id_raw.isdigit() or not secret or len(secret) > 128:
        raise PasswordResetError("Ссылка недействительна или уже использована.")

    with transaction.atomic():
        flow = (
            PasswordResetRequest.objects.select_for_update()
            .select_related("user")
            .filter(pk=int(flow_id_raw), user_id=user_id)
            .first()
        )
        if flow is None or not flow.link_is_active:
            raise PasswordResetError("Ссылка недействительна или уже использована.")
        if flow.password_fingerprint != _password_fingerprint(flow.user):
            flow.revoked_at = timezone.now()
            flow.save(update_fields=["revoked_at", "updated_at"])
            raise PasswordResetError("Ссылка недействительна или уже использована.")
        if not check_password(secret, flow.token_hash):
            raise PasswordResetError("Ссылка недействительна или уже использована.")

        flow.opened_at = timezone.now()
        flow.save(update_fields=["opened_at", "updated_at"])
        return flow


def get_opened_password_reset(flow_id: int) -> PasswordResetRequest | None:
    flow = (
        PasswordResetRequest.objects.select_related("user")
        .filter(
            pk=flow_id,
            opened_at__isnull=False,
            revoked_at__isnull=True,
            completed_at__isnull=True,
        )
        .first()
    )
    if flow is None or flow.is_expired:
        return None
    if flow.password_fingerprint != _password_fingerprint(flow.user):
        return None
    return flow


def complete_password_reset(flow_id: int, new_password: str) -> PasswordResetRequest:
    with transaction.atomic():
        flow = (
            PasswordResetRequest.objects.select_for_update()
            .select_related("user")
            .filter(
                pk=flow_id,
                opened_at__isnull=False,
                revoked_at__isnull=True,
                completed_at__isnull=True,
            )
            .first()
        )
        if flow is None or flow.is_expired:
            raise PasswordResetError("Сеанс восстановления пароля недействителен.")
        if flow.password_fingerprint != _password_fingerprint(flow.user):
            raise PasswordResetError("Сеанс восстановления пароля недействителен.")

        flow.user.set_password(new_password)
        flow.user.save(update_fields=["password"])
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
    send_account_email(
        subject="Код подтверждения почты на КапперХаб",
        template_name="account_email/new_email_code.txt",
        to_email=flow.new_email,
        context={
            "user": flow.user,
            "code": code,
            "new_email": flow.new_email,
            "expires_minutes": EMAIL_REQUEST_TTL_MINUTES,
        },
    )
    return code


def _active_flow(user: User):
    return EmailChangeRequest.objects.filter(user=user, completed_at__isnull=True)


def _ensure_email_available(email: str, *, user: User) -> None:
    if User.objects.filter(email__iexact=email).exclude(pk=user.pk).exists():
        raise EmailChangeError("Пользователь с такой почтой уже существует.")


def _expires_at():
    return timezone.now() + timedelta(minutes=EMAIL_REQUEST_TTL_MINUTES)


def _password_fingerprint(user: User) -> str:
    return hashlib.sha256((user.password or "").encode("utf-8")).hexdigest()
