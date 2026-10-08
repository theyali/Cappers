import time
import urllib.parse

from django.core.management.base import BaseCommand, CommandError

from notifications.models import NotificationPreference, TelegramAccount
from notifications.telegram_bot import api_call, get_bot_token, telegram_webapp_url


class Command(BaseCommand):
    help = (
        "Return to the bot's common menu button every chat whose own button opens another "
        "site, such as the old domain. Telegram keeps such a button stuck on loading."
    )

    def handle(self, *args, **options):
        if not get_bot_token():
            raise CommandError("TG_BOT_TOKEN не настроен")
        site_host = urllib.parse.urlsplit(telegram_webapp_url()).netloc
        if not site_host:
            raise CommandError("SITE_BASE_URL должен быть https-адресом")

        chat_ids = set(TelegramAccount.objects.values_list("chat_id", flat=True))
        chat_ids.update(
            NotificationPreference.objects.exclude(telegram_chat_id="").values_list("telegram_chat_id", flat=True)
        )

        reset, failed, old_urls = 0, 0, set()
        for chat_id in sorted(chat_ids):
            # Telegram allows about 30 requests a second.
            time.sleep(0.05)
            try:
                button = api_call("getChatMenuButton", {"chat_id": int(chat_id)}) or {}
                url = (button.get("web_app") or {}).get("url", "")
                if button.get("type") == "default" or urllib.parse.urlsplit(url).netloc == site_host:
                    continue
                api_call("setChatMenuButton", {"chat_id": int(chat_id), "menu_button": {"type": "default"}})
            except (OSError, RuntimeError, ValueError) as error:
                # The user blocked the bot or deleted the chat: nothing to fix there.
                failed += 1
                self.stderr.write(f"Чат {chat_id}: {error}")
                continue
            reset += 1
            old_urls.add(url or button.get("type", ""))

        for url in sorted(old_urls):
            self.stdout.write(f"Было: {url}")
        self.stdout.write(
            self.style.SUCCESS(f"Чатов: {len(chat_ids)}, кнопка сброшена: {reset}, ошибок: {failed}")
        )
