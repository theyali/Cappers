"""Autoposting to a capper's Telegram channel.

The capper adds the bot as a channel admin; the bot learns about it from the my_chat_member update
and links the channel to the site account of the Telegram user who added it. New coupons are posted
with their card and a link to the site, and the result of every announced coupon goes as a reply to
its post, losses included, so the channel's record matches the site's statistics.
"""

import logging
from collections import Counter
from html import escape
from urllib.parse import urlencode

from django.conf import settings
from django.db import transaction
from django.urls import reverse

from cabinet.models import User
from cabinet.vip import plural_ru
from game.models import PredictionCoupon

from .models import TelegramAccount, TelegramChannel, TelegramChannelPost
from .telegram_bot import TelegramApiError, api_call, api_upload, send_message

logger = logging.getLogger(__name__)

# Rights asked for when the capper adds the bot from the site's link.
ADD_BOT_RIGHTS = "post_messages"
SPORT_EMOJI = {"f": "⚽", "t": "🎾", "b": "🏀", "h": "🏒", "e": "🎮", "v": "🏐"}
RESULT_TITLES = {
    PredictionCoupon.StateStatus.WIN: ("✅", "{noun} зашёл"),
    PredictionCoupon.StateStatus.LOSE: ("❌", "{noun} не зашёл"),
    PredictionCoupon.StateStatus.REFUND: ("↩️", "{noun}: возврат"),
}
# A photo caption holds up to 1024 characters.
EXPRESS_LINES = 8


def build_channel_settings_context(user) -> dict:
    channel = TelegramChannel.objects.filter(user=user).first()
    return {
        "telegram_channel": channel,
        "telegram_channel_results": _results_line(_result_counts(channel)) if channel else "",
    }


def _notify(telegram_user_id: str, text: str) -> None:
    # Telegram refuses when the person never opened the bot; the site shows the state anyway.
    try:
        send_message(telegram_user_id, text)
    except Exception as error:
        logger.info("Channel notice to %s not sent: %s", telegram_user_id, error)


def sync_channel_membership(update: dict) -> TelegramChannel | None:
    """my_chat_member: link the channel when the bot may post there, switch it off when it may not."""
    chat = update.get("chat") or {}
    if chat.get("type") != "channel":
        return None
    chat_id = str(chat.get("id") or "")
    member = update.get("new_chat_member") or {}
    if member.get("status") != "administrator" or not member.get("can_post_messages"):
        reason = "У бота нет права публиковать сообщения" if member.get("status") == "administrator" else "Бот удалён из канала"
        TelegramChannel.objects.filter(chat_id=chat_id).update(is_active=False, last_error=reason)
        return None

    adder_id = str((update.get("from") or {}).get("id") or "")
    details = {"title": str(chat.get("title") or "")[:255], "username": str(chat.get("username") or "")[:80]}
    account = (
        TelegramAccount.objects.select_related("user")
        .filter(chat_id=adder_id, user__role=User.Role.ANALYST)
        .first()
    )
    if account is None:
        # Rights given back by another admin of a channel that a capper already linked.
        if TelegramChannel.objects.filter(chat_id=chat_id).update(is_active=True, last_error="", **details):
            return TelegramChannel.objects.get(chat_id=chat_id)
        _notify(adder_id, (
            "Канал не подключён: этот Telegram не связан с аккаунтом каппера КапперХаб.\n\n"
            "Войдите на сайт через Telegram или подключите его в настройках профиля, "
            "затем добавьте бота в канал ещё раз."
        ))
        return None

    with transaction.atomic():
        # One channel per capper and one capper per channel; the old pair's posts go with it.
        TelegramChannel.objects.filter(user=account.user).exclude(chat_id=chat_id).delete()
        TelegramChannel.objects.filter(chat_id=chat_id).exclude(user=account.user).delete()
        channel, _ = TelegramChannel.objects.update_or_create(
            chat_id=chat_id,
            defaults={"user": account.user, "is_active": True, "last_error": "", **details},
        )
    _notify(adder_id, (
        f"Канал «{channel.title}» подключён к КапперХаб.\n\n"
        "Новые прогнозы и их итоги будут публиковаться в нём автоматически."
    ))
    return channel


def disconnect_channel(user) -> None:
    channel = TelegramChannel.objects.filter(user=user).first()
    if channel is None:
        return
    try:
        api_call("leaveChat", {"chat_id": channel.chat_id})
    except Exception as error:
        logger.info("Bot did not leave channel %s: %s", channel.chat_id, error)
    channel.delete()


# Posts ---------------------------------------------------------------------------------------

def _site_url(path: str, campaign: str) -> str:
    query = urlencode({"utm_source": "telegram", "utm_medium": "channel", "utm_campaign": campaign})
    return f"{settings.SITE_BASE_URL.rstrip('/')}{path}?{query}"


def _result_counts(channel, *, without=None) -> Counter:
    posts = channel.posts.filter(kind=TelegramChannelPost.Kind.RESULT).exclude(message_id=None)
    if without is not None:
        posts = posts.exclude(pk=without.pk)
    return Counter(posts.values_list("state", flat=True))


def _results_line(states: Counter) -> str:
    if not states:
        return ""
    counts = " · ".join(f"{states[state]} {emoji}" for state, (emoji, _title) in RESULT_TITLES.items())
    return f"Итоги в канале: {counts}"


def _event_lines(data: dict, *, with_score: bool) -> list[str]:
    events = data["events"]
    lines = []
    if len(events) == 1:
        event = events[0]
        score = f" · {event['score']}" if with_score and event["score"] else ""
        lines.append(f"{SPORT_EMOJI.get(event['sport'], '🏆')} <b>{escape(event['title'])}</b>{escape(score)}")
        meta = " · ".join(part for part in (event["league"], event["when"]) if part)
        if meta:
            lines.append(escape(meta))
        if event["pick"]:
            lines.append(f"Ставка: <b>{escape(event['pick'])}</b> · кэф <b>{event['coefficient']}</b>")
        return lines
    for event in events[:EXPRESS_LINES]:
        parts = [escape(event["title"])]
        if with_score and event["score"]:
            parts.append(escape(event["score"]))
        if event["pick"]:
            parts.append(f"<b>{escape(event['pick'])}</b> · {event['coefficient']}")
        lines.append(f"{SPORT_EMOJI.get(event['sport'], '🏆')} " + " · ".join(parts))
    if len(events) > EXPRESS_LINES:
        more = len(events) - EXPRESS_LINES
        lines.append(f"…и ещё {more} {plural_ru(more, 'событие', 'события', 'событий')}")
    return lines


def _with_coefficient(head: str, data: dict) -> str:
    """An express shows its total odds in the head; a single shows them in its event line."""
    if len(data["events"]) > 1 and data["coefficient"]:
        return f"{head} · кэф <b>{data['coefficient']}</b>"
    return head


def build_prediction_caption(data: dict) -> str:
    count = len(data["events"])
    kind = f"экспресс · {count} {plural_ru(count, 'событие', 'события', 'событий')}" if count > 1 else "прогноз"
    head = f"🔒 <b>Платный {kind}</b>" if data["locked"] else _with_coefficient(f"🔥 <b>Новый {kind}</b>", data)
    lines = [head, "", *_event_lines(data, with_score=False)]
    if data["locked"]:
        offer = escape(data.get("offer") or "")
        lines += ["", f"{offer}: <b>{escape(data['price'])}</b>" if data.get("price") else offer]
    return "\n".join(lines)


def build_result_caption(data: dict, results_line: str, *, corrected: bool) -> str:
    emoji, title = RESULT_TITLES[data["state"]]
    noun = "Экспресс" if len(data["events"]) > 1 else "Прогноз"
    head = _with_coefficient(f"{emoji} <b>{title.format(noun=noun)}</b>", data)
    lines = [head, "", *_event_lines(data, with_score=True)]
    if corrected:
        lines[:0] = ["<i>Итог пересчитан</i>"]
    if results_line:
        lines += ["", results_line]
    return "\n".join(lines)


def _send_post(channel, coupon, caption: str, button: dict, reply_to: int | None) -> int:
    from front.og_cards.data import coupon_card_png

    payload = {
        "chat_id": channel.chat_id,
        "caption": caption,
        "parse_mode": "HTML",
        "reply_markup": {"inline_keyboard": [[button]]},
    }
    if reply_to:
        payload["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
    message = api_upload("sendPhoto", payload, {"photo": (f"coupon-{coupon.pk}.png", coupon_card_png(coupon), "image/png")})
    return int(message["message_id"])


def publish_channel_post(coupon_id: int, kind: str) -> TelegramChannelPost | None:
    """Post a coupon (kind PREDICTION) or its result (kind RESULT) to its author's channel, once."""
    from front.og_cards.data import card_coupons, coupon_card_data

    coupon = card_coupons().select_related("author__telegram_channel").filter(pk=coupon_id).first()
    channel = getattr(coupon.author, "telegram_channel", None) if coupon else None
    if channel is None or not channel.is_active:
        return None
    data = coupon_card_data(coupon, coupon.card_positions)
    campaign = coupon.author.username
    if kind == TelegramChannelPost.Kind.PREDICTION:
        if data["locked"] and not channel.post_paid:
            return None
        reply_to = None
    else:
        if coupon.state_status not in RESULT_TITLES:
            return None
        # Only coupons announced in the channel get a result there.
        reply_to = (
            channel.posts.filter(coupon=coupon, kind=TelegramChannelPost.Kind.PREDICTION)
            .exclude(message_id=None)
            .values_list("message_id", flat=True)
            .first()
        )
        if reply_to is None:
            return None

    post, created = TelegramChannelPost.objects.get_or_create(channel=channel, coupon=coupon, kind=kind)
    if not created and (kind == TelegramChannelPost.Kind.PREDICTION or post.state == coupon.state_status):
        return None
    previous_state = post.state
    post.state = coupon.state_status
    if kind == TelegramChannelPost.Kind.PREDICTION:
        caption = build_prediction_caption(data)
        button_text = "🔓 Открыть доступ" if data["locked"] else "📊 Открыть прогноз"
        button = {"text": button_text, "url": _site_url(reverse("front:prediction_detail", args=[coupon.pk]), campaign)}
    else:
        # The line already counts the result being sent.
        states = _result_counts(channel, without=post)
        states[coupon.state_status] += 1
        caption = build_result_caption(data, _results_line(states), corrected=not created)
        button = {"text": "📈 Статистика каппера", "url": _site_url(reverse("front:expert_profile", args=[campaign]), campaign)}

    try:
        message_id = _send_post(channel, coupon, caption, button, reply_to)
    except TelegramApiError as error:
        if created:
            post.delete()
        if error.code in (400, 403) and not error.retry_after:
            # Removed from the channel or the rights were taken away: stop until the capper fixes it.
            TelegramChannel.objects.filter(pk=channel.pk).update(is_active=False, last_error=str(error)[:255])
            logger.warning("Channel %s refused post of coupon %s: %s", channel.chat_id, coupon.pk, error)
            return None
        raise
    except Exception:
        if created:
            post.delete()
        else:
            post.state = previous_state
        raise
    post.message_id = message_id
    post.save(update_fields=["message_id", "state"])
    return post
