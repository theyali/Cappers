from django.core.management.base import BaseCommand

from bots.services import run_bot_activity, run_bot_predictions


class Command(BaseCommand):
    help = "Запускает один цикл активности ботов."

    def add_arguments(self, parser):
        parser.add_argument(
            "--only",
            choices=("all", "predictions", "activity"),
            default="all",
        )
        parser.add_argument("--max-actions", type=int, default=80)

    def handle(self, *args, **options):
        if options["only"] in {"all", "predictions"}:
            self.stdout.write(self.style.SUCCESS(f"Прогнозы: {run_bot_predictions()}"))
        if options["only"] in {"all", "activity"}:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Активность: {run_bot_activity(max_actions=options['max_actions'])}"
                )
            )
