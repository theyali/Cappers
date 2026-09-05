from django.core.management.base import BaseCommand, CommandError

from bots.models import BotAccount, BotRuntimeControl
from bots.services import (
    cleanup_bot_runtime_data,
    get_bot_runtime_status,
    reset_stale_bot_planned_actions,
    set_bot_runtime_mode,
)


class Command(BaseCommand):
    help = "Управляет runtime-режимом ботов, очисткой и зависшими действиями очереди."

    def add_arguments(self, parser):
        mode_group = parser.add_mutually_exclusive_group()
        mode_group.add_argument("--pause", action="store_true", help="Приостановить все bot-циклы.")
        mode_group.add_argument("--resume", action="store_true", help="Включить все bot-циклы.")
        mode_group.add_argument("--only-presence", action="store_true", help="Оставить включенным только онлайн.")
        mode_group.add_argument("--only-tournaments", action="store_true", help="Оставить включенными только турниры.")
        mode_group.add_argument(
            "--mode",
            choices=[choice for choice, _ in BotRuntimeControl.Mode.choices],
            help="Установить runtime-режим напрямую.",
        )
        parser.add_argument("--note", default="", help="Заметка к изменению режима.")
        parser.add_argument("--status", action="store_true", help="Показать текущий runtime-режим.")
        parser.add_argument(
            "--activate-all-bots",
            action="store_true",
            help="Поставить is_active=True всем bot-аккаунтам.",
        )
        parser.add_argument(
            "--deactivate-all-bots",
            action="store_true",
            help="Поставить is_active=False всем bot-аккаунтам.",
        )
        parser.add_argument("--reset-running", action="store_true", help="Сбросить зависшие running в pending.")
        parser.add_argument("--older-minutes", type=int, default=30)
        parser.add_argument("--cleanup", action="store_true", help="Удалить старые done/skipped и bot-сессии.")
        parser.add_argument("--planned-days", type=int, default=14)
        parser.add_argument("--sessions-days", type=int, default=14)

    def handle(self, *args, **options):
        if options["activate_all_bots"] and options["deactivate_all_bots"]:
            raise CommandError("Нельзя одновременно включить и выключить всех ботов.")

        mode = self._requested_mode(options)
        if mode:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Режим: {set_bot_runtime_mode(mode, note=options['note'])}"
                )
            )

        if options["activate_all_bots"]:
            self.stdout.write(
                self.style.SUCCESS(f"Активировано ботов: {BotAccount.objects.update(is_active=True)}")
            )
        if options["deactivate_all_bots"]:
            self.stdout.write(
                self.style.SUCCESS(f"Деактивировано ботов: {BotAccount.objects.update(is_active=False)}")
            )

        if options["reset_running"]:
            self.stdout.write(
                self.style.SUCCESS(
                    "Сброс running: "
                    f"{reset_stale_bot_planned_actions(older_minutes=options['older_minutes'])}"
                )
            )

        if options["cleanup"]:
            self.stdout.write(
                self.style.SUCCESS(
                    "Cleanup: "
                    f"{cleanup_bot_runtime_data(planned_days=options['planned_days'], sessions_days=options['sessions_days'])}"
                )
            )

        if options["status"] or not self._has_action(options):
            self.stdout.write(self.style.SUCCESS(f"Статус: {get_bot_runtime_status()}"))

    def _requested_mode(self, options):
        if options["pause"]:
            return BotRuntimeControl.Mode.PAUSED
        if options["resume"]:
            return BotRuntimeControl.Mode.ALL
        if options["only_presence"]:
            return BotRuntimeControl.Mode.PRESENCE_ONLY
        if options["only_tournaments"]:
            return BotRuntimeControl.Mode.TOURNAMENTS_ONLY
        return options["mode"]

    def _has_action(self, options) -> bool:
        return any(
            [
                options["pause"],
                options["resume"],
                options["only_presence"],
                options["only_tournaments"],
                options["mode"],
                options["activate_all_bots"],
                options["deactivate_all_bots"],
                options["reset_running"],
                options["cleanup"],
                options["status"],
            ]
        )
