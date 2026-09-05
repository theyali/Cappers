from django.core.management.base import BaseCommand

from bots.services import (
    plan_bot_tournament_activity,
    preview_bot_predictions,
    preview_bot_tournament_activity,
    run_bot_activity,
    run_bot_planned_actions,
    run_bot_predictions,
    run_bot_presence_activity,
    run_bot_tournament_activity,
)


class Command(BaseCommand):
    help = "Запускает один цикл активности ботов."

    def add_arguments(self, parser):
        parser.add_argument(
            "--only",
            choices=("all", "predictions", "activity", "planned", "presence", "tournaments"),
            default="all",
        )
        parser.add_argument("--max-actions", type=int, default=80)
        parser.add_argument("--max-planned-actions", type=int, default=30)
        parser.add_argument(
            "--execute-now",
            action="store_true",
            help="Выполнить прогнозы/активность сразу, минуя очередь.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Показать, что сделали бы боты, без публикации, очереди и вступлений.",
        )
        parser.add_argument("--preview-limit", type=int, default=10)

    def handle(self, *args, **options):
        if options["dry_run"]:
            if options["only"] == "tournaments":
                self.stdout.write(
                    self.style.SUCCESS(
                        "Dry-run турниры: "
                        f"{preview_bot_tournament_activity(limit=options['preview_limit'])}"
                    )
                )
                return
            self.stdout.write(
                self.style.SUCCESS(
                    f"Dry-run прогнозы: {preview_bot_predictions(limit=options['preview_limit'])}"
                )
            )
            return

        if options["only"] in {"all", "predictions"}:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Прогнозы: {run_bot_predictions(execute_immediately=options['execute_now'])}"
                )
            )
        if options["only"] in {"all", "activity"}:
            self.stdout.write(
                self.style.SUCCESS(
                    "Активность: "
                    f"{run_bot_activity(max_actions=options['max_actions'], execute_immediately=options['execute_now'])}"
                )
            )
        if options["only"] in {"all", "planned"}:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Очередь: {run_bot_planned_actions(max_actions=options['max_planned_actions'])}"
                )
            )
        if options["only"] in {"all", "presence"}:
            self.stdout.write(
                self.style.SUCCESS(f"Онлайн: {run_bot_presence_activity()}")
            )
        if options["only"] in {"all", "tournaments"}:
            result = (
                run_bot_tournament_activity()
                if options["execute_now"]
                else plan_bot_tournament_activity()
            )
            self.stdout.write(
                self.style.SUCCESS(f"Турниры: {result}")
            )
