import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_http_methods

from notifications.telegram_bot import (
    TelegramAlreadyLinkedError,
    connect_verified_telegram_account,
    find_linked_user_by_chat_id,
)

from .models import User


TELEGRAM_FIELDS = (
    "id",
    "first_name",
    "last_name",
    "username",
    "photo_url",
    "auth_date",
)


class TelegramIdentityConflict(Exception):
    pass


def _telegram_bot_id() -> str:
    token = (getattr(settings, "TG_BOT_TOKEN", "") or "").strip()
    bot_id = token.partition(":")[0].strip()
    return bot_id if bot_id.isdigit() else ""


class TelegramAwareLoginView(auth_views.LoginView):
    template_name = "cabinet/auth/login.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["telegram_bot_id"] = _telegram_bot_id()
        context["telegram_auth_url"] = reverse("cabinet:telegram_login")

        next_url = self.request.GET.get(self.redirect_field_name, "")
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={self.request.get_host()},
            require_https=self.request.is_secure(),
        ):
            self.request.session["telegram_login_next"] = next_url
        else:
            self.request.session.pop("telegram_login_next", None)

        return context


def _telegram_payload(request):
    return {
        key: request.GET[key]
        for key in TELEGRAM_FIELDS
        if key in request.GET and request.GET[key] != ""
    }


def _telegram_signature_is_valid(payload: dict[str, str], received_hash: str) -> bool:
    token = getattr(settings, "TG_BOT_TOKEN", "") or ""
    if not token or not received_hash:
        return False

    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(payload.items())
    )
    secret_key = hashlib.sha256(token.encode("utf-8")).digest()
    expected_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected_hash, received_hash)


def _telegram_auth_date_is_fresh(value) -> bool:
    try:
        auth_date = int(value)
    except (TypeError, ValueError):
        return False

    max_age = max(60, int(getattr(settings, "TELEGRAM_AUTH_MAX_AGE", 900)))
    age = int(time.time()) - auth_date
    return 0 <= age <= max_age


def _telegram_auth_is_fresh(payload: dict[str, str]) -> bool:
    return _telegram_auth_date_is_fresh(payload.get("auth_date"))


def _new_telegram_username(telegram_id: int) -> str:
    base = f"tg_{telegram_id}"
    candidate = base
    suffix = 1
    while User.objects.filter(username=candidate).exists():
        suffix += 1
        candidate = f"{base}_{suffix}"
    return candidate


def _resolve_telegram_user(payload: dict) -> User:
    try:
        telegram_id = int(payload["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise TelegramIdentityConflict(
            "Telegram не передал идентификатор пользователя."
        ) from exc

    defaults = {
        "telegram_username": str(payload.get("username") or "")[:150],
        "first_name": str(payload.get("first_name") or "")[:150],
        "last_name": str(payload.get("last_name") or "")[:150],
    }

    user = User.objects.filter(telegram_id=telegram_id).first()
    linked_user = find_linked_user_by_chat_id(str(telegram_id))

    if user and linked_user and user.pk != linked_user.pk:
        raise TelegramIdentityConflict("Этот Telegram уже связан с другим профилем.")

    if user is None and linked_user is not None:
        if linked_user.telegram_id not in {None, telegram_id}:
            raise TelegramIdentityConflict(
                "Этот профиль уже связан с другим Telegram."
            )
        user = linked_user

    if user is None:
        user = User(
            username=_new_telegram_username(telegram_id),
            telegram_id=telegram_id,
            **defaults,
        )
        user.set_unusable_password()
        user.save()
    else:
        changed_fields = []
        if user.telegram_id is None:
            user.telegram_id = telegram_id
            changed_fields.append("telegram_id")
        for field, value in defaults.items():
            if getattr(user, field) != value:
                setattr(user, field, value)
                changed_fields.append(field)
        if changed_fields:
            user.save(update_fields=changed_fields)

    if not user.is_active:
        raise TelegramIdentityConflict("Этот аккаунт отключён.")

    try:
        connect_verified_telegram_account(
            user,
            chat_id=str(telegram_id),
            telegram_username=payload.get("username", ""),
            telegram_user=payload,
            enable_notifications=True,
        )
    except TelegramAlreadyLinkedError as exc:
        raise TelegramIdentityConflict(
            "Этот Telegram уже связан с другим профилем."
        ) from exc

    return user


def _safe_next_url(request, candidate: str | None, default: str | None = None) -> str:
    default = default or reverse("cabinet:dashboard")
    candidate = str(candidate or "").strip()
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return default


def _parse_webapp_init_data(init_data: str) -> dict | None:
    token = (getattr(settings, "TG_BOT_TOKEN", "") or "").strip()
    if not token or not init_data:
        return None

    values = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = values.pop("hash", "")
    if not received_hash:
        return None

    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(values.items())
    )
    secret_key = hmac.new(
        b"WebAppData",
        token.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    expected_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        return None

    if not _telegram_auth_date_is_fresh(values.get("auth_date")):
        return None

    try:
        telegram_user = json.loads(values.get("user") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return None

    if not isinstance(telegram_user, dict) or not telegram_user.get("id"):
        return None

    telegram_user["auth_date"] = values.get("auth_date", "")
    return telegram_user


@require_GET
def telegram_login(request):
    bot_token = (getattr(settings, "TG_BOT_TOKEN", "") or "").strip()
    if not bot_token:
        messages.error(request, "Вход через Telegram пока не настроен.")
        return redirect("cabinet:login")

    payload = _telegram_payload(request)
    received_hash = request.GET.get("hash", "")

    if not _telegram_signature_is_valid(payload, received_hash):
        messages.error(request, "Не удалось подтвердить данные Telegram.")
        return redirect("cabinet:login")

    if not _telegram_auth_is_fresh(payload):
        messages.error(request, "Авторизация Telegram устарела. Попробуйте ещё раз.")
        return redirect("cabinet:login")

    try:
        user = _resolve_telegram_user(payload)
    except TelegramIdentityConflict as exc:
        messages.error(request, str(exc))
        return redirect("cabinet:login")

    login(request, user)
    messages.success(
        request,
        "Вы вошли через Telegram. Telegram автоматически привязан к профилю.",
    )

    next_url = request.session.pop("telegram_login_next", "")
    return redirect(_safe_next_url(request, next_url))


@require_http_methods(["GET", "POST"])
def telegram_webapp_login(request):
    next_url = _safe_next_url(
        request,
        request.GET.get("next") if request.method == "GET" else request.POST.get("next"),
    )

    if request.method == "GET":
        return render(
            request,
            "cabinet/auth/telegram_webapp.html",
            {"next_url": next_url},
        )

    init_data = request.POST.get("init_data", "")
    telegram_user = _parse_webapp_init_data(init_data)
    if telegram_user is None:
        return JsonResponse(
            {
                "ok": False,
                "message": "Не удалось подтвердить вход через Telegram.",
            },
            status=403,
        )

    try:
        user = _resolve_telegram_user(telegram_user)
    except TelegramIdentityConflict as exc:
        return JsonResponse(
            {"ok": False, "message": str(exc)},
            status=409,
        )

    login(request, user)
    return JsonResponse(
        {
            "ok": True,
            "redirect": next_url,
        }
    )
