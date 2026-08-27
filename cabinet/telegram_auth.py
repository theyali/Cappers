import hashlib
import hmac
import time

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET

from .models import User


TELEGRAM_FIELDS = (
    "id",
    "first_name",
    "last_name",
    "username",
    "photo_url",
    "auth_date",
)


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


def _telegram_auth_is_fresh(payload: dict[str, str]) -> bool:
    try:
        auth_date = int(payload["auth_date"])
    except (KeyError, TypeError, ValueError):
        return False

    max_age = max(60, int(getattr(settings, "TELEGRAM_AUTH_MAX_AGE", 900)))
    age = int(time.time()) - auth_date
    return 0 <= age <= max_age


def _new_telegram_username(telegram_id: int) -> str:
    base = f"tg_{telegram_id}"
    candidate = base
    suffix = 1
    while User.objects.filter(username=candidate).exists():
        suffix += 1
        candidate = f"{base}_{suffix}"
    return candidate


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
        telegram_id = int(payload["id"])
    except (KeyError, TypeError, ValueError):
        messages.error(request, "Telegram не передал идентификатор пользователя.")
        return redirect("cabinet:login")

    defaults = {
        "telegram_username": payload.get("username", "")[:150],
        "first_name": payload.get("first_name", "")[:150],
        "last_name": payload.get("last_name", "")[:150],
    }
    user = User.objects.filter(telegram_id=telegram_id).first()

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
        for field, value in defaults.items():
            if getattr(user, field) != value:
                setattr(user, field, value)
                changed_fields.append(field)
        if changed_fields:
            user.save(update_fields=changed_fields)

    if not user.is_active:
        messages.error(request, "Этот аккаунт отключён.")
        return redirect("cabinet:login")

    login(request, user)
    messages.success(request, "Вы вошли через Telegram.")

    next_url = request.session.pop("telegram_login_next", "")
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(next_url)
    return redirect(settings.LOGIN_REDIRECT_URL)
