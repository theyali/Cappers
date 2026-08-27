import time

from django.core.management.base import BaseCommand, CommandError

from notifications.telegram_bot import (
    TelegramAlreadyLinkedError,
    api_call,
    consume_link_payload,
    find_linked_user_by_chat_id,
    get_bot_token,
    get_bot_username,
    send_message,
    telegram_webapp_url,
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
                    {"command": "start", "description": "Проверить аккаунт"},
                    {"command": "login", "description": "Войти на сайт"},
                    {"command": "site", "description": "Открыть сайт"},
                    {"command": "profile", "description": "Открыть профиль"},
                    {"command": "notifications", "description": "Открыть уведомления"},
                    {"command": "help", "description": "Помощь"},
                ]
            },
        )
        api_call(
            "setChatMenuButton",
            {
                "menu_button": web_app_menu_button(
                    telegram_webapp_url("/cabinet/")
                )
            },
        )
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

    def _set_menu(self, chat_id: str, next_path: str = "/cabinet/") -> None:
        target = telegram_webapp_url(next_path)
        api_call(
            "setChatMenuButton",
            {
                "chat_id": int(chat_id),
                "menu_button": web_app_menu_button(target),
            },
        )

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
        supported_commands = {
            "/start",
            "/login",
            "/site",
            "/profile",
            "/notifications",
            "/help",
        }
        if command not in supported_commands:
            return

        chat_id = str(chat.get("id") or "")
        if not chat_id:
            return

        telegram_user = message.get("from") or {}
        telegram_username = str(telegram_user.get("username") or "")
        argument = argument.strip()

        if command == "/start" and argument.startswith("link_"):
            self._handle_link(
                chat_id,
                argument,
                telegram_username=telegram_username,
                telegram_user=telegram_user,
            )
            return

        linked_user = find_linked_user_by_chat_id(chat_id)

        if command == "/profile":
            self._set_menu(chat_id, "/cabinet/profile/")
            reply = (
                "Профиль готов к открытию.\n\n"
                "Нажмите единственную кнопку «Открыть сайт» рядом с полем сообщения — "
                "вход выполнится автоматически через Telegram."
            )
        elif command == "/notifications":
            self._set_menu(chat_id, "/notifications/")
            reply = (
                "Открываю центр уведомлений.\n\n"
                "Нажмите «Открыть сайт» — повторно вводить логин и пароль не нужно."
            )
        elif command in {"/login", "/site"}:
            self._set_menu(chat_id, "/cabinet/")
            if linked_user:
                display_name = linked_user.get_full_name() or linked_user.username
                reply = (
                    f"Аккаунт найден: {display_name}.\n\n"
                    "Нажмите «Открыть сайт». Telegram подтвердит вас автоматически, "
                    "и сайт откроется уже после входа."
                )
            else:
                reply = (
                    "Нажмите «Открыть сайт».\n\n"
                    "Telegram передаст сайту подписанные данные. "
                    "Если аккаунта ещё нет, он будет создан и Telegram привяжется автоматически."
                )
        elif command == "/help":
            self._set_menu(chat_id, "/cabinet/")
            reply = (
                "Команды КапперХаб:\n\n"
                "/login — войти на сайт через Telegram\n"
                "/site — открыть сайт\n"
                "/profile — открыть профиль\n"
                "/notifications — открыть уведомления\n"
                "/start — проверить связь аккаунта\n\n"
                "Для входа используйте одну кнопку «Открыть сайт» рядом с полем сообщения."
            )
        else:
            self._set_menu(chat_id, "/cabinet/")
            if linked_user:
                display_name = linked_user.get_full_name() or linked_user.username
                reply = (
                    f"Telegram связан с аккаунтом: {display_name}.\n\n"
                    "Всё готово. Нажмите «Открыть сайт» — "
                    "сайт откроется уже авторизованным."
                )
            else:
                reply = (
                    "Добро пожаловать в КапперХаб.\n\n"
                    "Нажмите «Открыть сайт» — вход выполнится через Telegram автоматически. "
                    "Отдельно привязывать Telegram в настройках не потребуется."
                )

        send_message(chat_id, reply, remove_keyboard=True)

    def _handle_link(
        self,
        chat_id: str,
        argument: str,
        *,
        telegram_username: str,
        telegram_user: dict,
    ) -> None:
        try:
            user = consume_link_payload(
                argument,
                chat_id=chat_id,
                telegram_username=telegram_username,
                telegram_user=telegram_user,
            )
        except TelegramAlreadyLinkedError as exc:
            display_name = exc.user.get_full_name() or exc.user.username
            self._set_menu(chat_id, "/cabinet/profile/")
            send_message(
                chat_id,
                (
                    "Этот Telegram уже подключён к аккаунту КапперХаб: "
                    f"{display_name}.\n\n"
                    "Используйте кнопку «Открыть сайт» — "
                    "повторный вход будет выполнен автоматически."
                ),
                remove_keyboard=True,
            )
            return

        if user:
            display_name = user.get_full_name() or user.username
            self._set_menu(chat_id, "/cabinet/profile/")
            send_message(
                chat_id,
                (
                    f"Telegram подключён к аккаунту КапперХаб: {display_name}.\n\n"
                    "Уведомления включены. Нажмите «Открыть сайт» — "
                    "профиль откроется уже после входа."
                ),
                remove_keyboard=True,
            )
            return

        self._set_menu(chat_id, "/cabinet/")
        send_message(
            chat_id,
            (
                "Ссылка подключения устарела или уже использована.\n\n"
                "Теперь ручная привязка не обязательна: "
                "нажмите «Открыть сайт», и Telegram выполнит вход автоматически."
            ),
            remove_keyboard=True,
        )
