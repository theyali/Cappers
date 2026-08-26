from django.core.management.base import BaseCommand

from bots.services import create_history, run_bot_activity, run_bot_predictions, seed_bots


class Command(BaseCommand):
    help = "Создает демо-ботов, экспертов и стартовую активность."

    def add_arguments(self, parser):
        parser.add_argument("--readers", type=int, default=40)
        parser.add_argument("--experts", type=int, default=20)
        parser.add_argument("--no-history", action="store_true")
        parser.add_argument("--no-initial-run", action="store_true")

    def handle(self, *args, **options):
        seed_result = seed_bots(
            reader_count=options["readers"],
            expert_count=options["experts"],
        )
        self.stdout.write(self.style.SUCCESS(f"Боты: {seed_result}"))

        if not options["no_history"]:
            history_result = create_history()
            self.stdout.write(self.style.SUCCESS(f"История: {history_result}"))

        if not options["no_initial_run"]:
            prediction_result = run_bot_predictions()
            activity_result = run_bot_activity()
            self.stdout.write(self.style.SUCCESS(f"Прогнозы: {prediction_result}"))
            self.stdout.write(self.style.SUCCESS(f"Активность: {activity_result}"))
