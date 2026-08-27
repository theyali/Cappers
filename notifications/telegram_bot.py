import hashlib
import json
import secrets
import urllib.parse
import urllib.request
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from .models import NotificationPreference, TelegramAccount, TelegramLinkToken


BOT_USERNAME_CACHE_KEY = "notifications:telegram_bot_username"
LINK_TTL_MINUTES = 15


class TelegramAlreadyLinkedError(Exception):
    def __init__(self, user):
        self.user = user
        display_name = user.get_full_name() or user.username
        super().__init__(f"Telegram уже подключён к аккаунту {display_name}")


def get_bot_token() -> str:
    return (
        getattr(settings, "TG_BOT_TOKEN", "")
        or getattr(settings, "TELEGRAM_BOT_TOKEN", "")
    ).strip()


def api_call(method: str, payload: dict | None = None, *, timeout: int = 15):
    token = get_bot_token()
    if not token:
        raise RuntimeError("TG_BOT_TOKEN не настроен")

    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/{method}",
        data=json.dumps(payload or {}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))

    if not data.get("ok"):
        raise RuntimeError(data.get("description") or f"Telegram API error: {method}")
    return data.get("result")


def get_bot_username(*, refresh: bool = False) -> str:
    if not refresh:
        cached = cache.get(BOT_USERNAME_CACHE_KEY)
        if cached:
            return cached

    me = api_call("getMe") or {}
    username = str(me.get("username") or "").strip()
    if not username:
        raise RuntimeError("Telegram bot username не найден")
    cache.set(BOT_USERNAME_CACHE_KEY, username, 6 * 60 * 60)
    return username


def _token_digest(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_link_payload(user) -> str:
    TelegramLinkToken.objects.filter(user=user, used_at__isnull=True).delete()
    raw_token = secrets.token_urlsafe(24)
    TelegramLinkToken.objects.create(
        user=user,
        token_hash=_token_digest(raw_token),
        expires_at=timezone.now() + timedelta(minutes=LINK_TTL_MINUTES),
    )
    return f"link_{raw_token}"


def build_connect_url(user) -> str:
    payload = create_link_payload(user)
    username = get_bot_username()
    return f"https://t.me/{username}?start={urllib.parse.quote(payload, safe='')}"


def find_linked_user_by_chat_id(chat_id: str):
    account = (
        TelegramAccount.objects.select_related("user")
        .filter(chat_id=str(chat_id))
        .first()
    )
    return account.user if account else None


def connect_verified_telegram_account(
    user,
    *,
    chat_id: str,
    telegram_username: str = "",
    telegram_user: dict | None = None,
    enable_notifications: bool = True,
):
    now = timezone.now()
    chat_id = str(chat_id)
    telegram_user = telegram_user or {}
    username = (
        telegram_username
        or str(telegram_user.get("username") or "")
    ).strip().lstrip("@")[:80]

    account_defaults = {
        "chat_id": chat_id,
        "username": username,
        "first_name": str(telegram_user.get("first_name") or "")[:120],
        "last_name": str(telegram_user.get("last_name") or "")[:120],
        "last_seen_at": now,
    }
    language_code = str(telegram_user.get("language_code") or "")[:12]
    if language_code:
        account_defaults["language_code"] = language_code

    with transaction.atomic():
        existing_account = (
            TelegramAccount.objects.select_for_update()
            .select_related("user")
            .filter(chat_id=chat_id)
            .exclude(user=user)
            .first()
        )
        if existing_account:
            raise TelegramAlreadyLinkedError(existing_account.user)

        account, _ = TelegramAccount.objects.update_or_create(
            user=user,
            defaults=account_defaults,
        )

        preferences, _ = NotificationPreference.objects.get_or_create(user=user)
        preferences.telegram_chat_id = chat_id
        preferences.telegram_username = username
        preferences.telegram_connected_at = now
        if enable_notifications:
            preferences.telegram_enabled = True
        preferences.save(
            update_fields=[
                "telegram_chat_id",
                "telegram_username",
                "telegram_connected_at",
                "telegram_enabled",
                "updated_at",
            ]
        )

    return account


def consume_link_payload(
    payload: str,
    *,
    chat_id: str,
    telegram_username: str = "",
    telegram_user: dict | None = None,
):
    if not payload.startswith("link_"):
        return None

    raw_token = payload[5:].strip()
    if not raw_token:
        return None

    now = timezone.now()
    digest = _token_digest(raw_token)

    with transaction.atomic():
        link = (
            TelegramLinkToken.objects.select_for_update()
            .select_related("user")
            .filter(token_hash=digest, used_at__isnull=True, expires_at__gt=now)
            .first()
        )
        if not link:
            return None

        connect_verified_telegram_account(
            link.user,
            chat_id=str(chat_id),
            telegram_username=telegram_username,
            telegram_user=telegram_user,
            enable_notifications=True,
        )

        link.used_at = now
        link.save(update_fields=["used_at"])

    return link.user


def disconnect_telegram(user) -> None:
    TelegramAccount.objects.filter(user=user).delete()
    preferences, _ = NotificationPreference.objects.get_or_create(user=user)
    preferences.telegram_chat_id = ""
    preferences.telegram_username = ""
    preferences.telegram_connected_at = None
    preferences.telegram_enabled = False
    preferences.save(
        update_fields=[
            "telegram_chat_id",
            "telegram_username",
            "telegram_connected_at",
            "telegram_enabled",
            "updated_at",
        ]
    )
    TelegramLinkToken.objects.filter(user=user, used_at__isnull=True).delete()


def _target_url(url: str | None = None) -> str:
    target = (url or getattr(settings, "SITE_BASE_URL", "")).strip()
    if not target:
        return ""
    return target


def open_button(url: str | None = None) -> dict:
    target = _target_url(url)
    if not target:
        return {}

    button = {"text": "Открыть Cappers"}
    if target.startswith("https://"):
        button["web_app"] = {"url": target}
    else:
        button["url"] = target
    return {"inline_keyboard": [[button]]}


def web_app_keyboard(url: str | None = None) -> dict:
    target = _target_url(url)
    if not target or not target.startswith("https://"):
        return {}
    return {
        "keyboard": [[{"text": "Открыть сайт", "web_app": {"url": target}}]],
        "resize_keyboard": True,
        "is_persistent": True,
    }


def web_app_menu_button(url: str | None = None) -> dict:
    target = _target_url(url)
    if not target or not target.startswith("https://"):
        return {"type": "commands"}
    return {
        "type": "web_app",
        "text": "Открыть сайт",
        "web_app": {"url": target},
    }


def send_message(chat_id: str, text: str, *, open_url: str | None = None) -> None:
    payload = {
        "chat_id": str(chat_id),
        "text": text,
        "disable_web_page_preview": True,
    }
    markup = web_app_keyboard(open_url) or open_button(open_url)
    if markup:
        payload["reply_markup"] = markup
    api_call("sendMessage", payload)
