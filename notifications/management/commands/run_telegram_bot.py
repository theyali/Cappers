import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from notifications.telegram_bot import (
    TelegramAlreadyLinkedError,
    api_call,
    consume_link_payload,
    get_bot_token,
    get_bot_username,
    send_message,
    web_app_menu_button,
)


class Command(BaseCommand):
    help = "Run Cappers Telegram bot via long polling."

    def handle(self, *args, **options):
        if not get_bot_token():
            raise CommandError("TG_BOT_TOKEN не настроен")

        api_call("deleteWebhook", {"drop_pending_updates": False})
        api_call(
            "setMyCommands",
            {
                "commands": [
                    {"command": "start", "description": "Открыть Cappers"},
                ]
            },
        )
        api_call("setChatMenuButton", {"menu_button": web_app_menu_button()})
        username = get_bot_username(refresh=True)
        self.stdout.write(self.style.SUCCESS(f"Telegram bot @{username} запущен"))

        offset = None
        while True:
            try:
                payload = {
                    "timeout": 30,
                    "allowed_updates": ["message"],
                }
                if offset is not None:
                    payload["offset"] = offset

                updates = api_call("getUpdates", payload, timeout=40) or []
                for update in updates:
                    offset = int(update.get("update_id", 0)) + 1
                    self._handle_update(update)
            except KeyboardInterrupt:
                self.stdout.write("Telegram bot остановлен")
                return
            except Exception as exc:
                self.stderr.write(f"Telegram polling error: {exc}")
                time.sleep(3)

    def _handle_update(self, update: dict) -> None:
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        if chat.get("type") != "private":
            return

        text = str(message.get("text") or "").strip()
        if not text:
            return

        command, _, argument = text.partition(" ")
        command = command.split("@", 1)[0].lower()
        if command != "/start":
            return

        chat_id = str(chat.get("id") or "")
        if not chat_id:
            return

        telegram_user = message.get("from") or {}
        telegram_username = str(telegram_user.get("username") or "")
        argument = argument.strip()

        if argument.startswith("link_"):
            try:
                user = consume_link_payload(
                    argument,
                    chat_id=chat_id,
                    telegram_username=telegram_username,
                    telegram_user=telegram_user,
                )
            except TelegramAlreadyLinkedError as exc:
                display_name = exc.user.get_full_name() or exc.user.username
                send_message(
                    chat_id,
                    (
                        "Этот Telegram уже подключён к аккаунту Cappers: "
                        f"{display_name}.\n\n"
                        "Один Telegram можно связать только с одним аккаунтом. "
                        "Сначала отключите Telegram в текущем профиле."
                    ),
                    open_url=f"{settings.SITE_BASE_URL.rstrip('/')}/notifications/",
                )
                return

            if user:
                display_name = user.get_full_name() or user.username
                send_message(
                    chat_id,
                    f"Telegram подключён к аккаунту Cappers: {display_name}.\n\nУведомления в Telegram включены.",
                    open_url=f"{settings.SITE_BASE_URL.rstrip('/')}/notifications/",
                )
                return

            send_message(
                chat_id,
                "Ссылка для подключения устарела или уже была использована. Откройте Cappers и подключите Telegram ещё раз.",
                open_url=f"{settings.SITE_BASE_URL.rstrip('/')}/notifications/",
            )
            return

        send_message(
            chat_id,
            "Cappers — прогнозы, матчи и уведомления в Telegram.\n\nЧтобы связать этот Telegram с аккаунтом, откройте профиль на сайте и нажмите «Подключить Telegram».",
            open_url=f"{settings.SITE_BASE_URL.rstrip('/')}/cabinet/profile/",
        )
