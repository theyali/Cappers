import json
import urllib.request
from html import escape

from django.conf import settings


KIND_PRESENTATION = {
    "new_prediction": ("🔥", "📊 Открыть прогноз"),
    "favorite_settled": ("✅", "📊 Открыть прогноз"),
    "match_prediction": ("🎯", "📊 Открыть прогноз"),
    "achievement": ("🏆", "👤 Открыть профиль"),
}

MATCH_EVENT_PRESENTATION = {
    "reminder": ("⏰", "⚽ Открыть матч"),
    "started": ("🟢", "⚽ Открыть матч"),
    "score": ("⚽", "⚽ Открыть матч"),
    "halftime": ("⏸️", "⚽ Открыть матч"),
    "finished": ("🏁", "⚽ Открыть матч"),
}

KNOWN_TITLE_EMOJIS = (
    "⚽",
    "🔥",
    "🏆",
    "✅",
    "❌",
    "↩️",
    "⏰",
    "🟢",
    "🏁",
    "⏸️",
    "📊",
    "🎯",
    "🔔",
)


def _presentation(notification) -> tuple[str, str]:
    meta = notification.meta if isinstance(notification.meta, dict) else {}

    if notification.kind == "match_reminder":
        event = str(meta.get("event") or "").strip().lower()
        return MATCH_EVENT_PRESENTATION.get(event, ("🔴", "⚽ Открыть матч"))

    if notification.kind == "favorite_settled":
        state = str(meta.get("state") or "").strip().lower()
        if state == "lose":
            return "❌", "📊 Открыть прогноз"
        if state == "refund":
            return "↩️", "📊 Открыть прогноз"

    return KIND_PRESENTATION.get(notification.kind, ("🔔", "Открыть в КапперХаб"))


def _clean_title(value: str) -> str:
    title = str(value or "").strip()
    changed = True
    while changed and title:
        changed = False
        for emoji in KNOWN_TITLE_EMOJIS:
            if title.startswith(emoji):
                title = title[len(emoji):].lstrip(" ·:-")
                changed = True
                break
    return title or "Новое уведомление"


def build_telegram_message(notification) -> tuple[str, str]:
    emoji, button_text = _presentation(notification)
    title = escape(_clean_title(notification.title))
    message = escape(str(notification.message or "").strip())

    parts = [f"{emoji} <b>{title}</b>"]
    if message:
        parts.extend(["", message])

    parts.extend(["", "<i>КапперХаб</i>"])
    return "\n".join(parts), button_text


def send_notification_to_telegram(chat_id: str, notification, link: str = "") -> None:
    token = getattr(settings, "TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN не настроен")

    text, button_text = build_telegram_message(notification)
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    if link.startswith(("http://", "https://")):
        payload["reply_markup"] = {
            "inline_keyboard": [[{"text": button_text, "url": link}]],
        }

    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        response.read()
