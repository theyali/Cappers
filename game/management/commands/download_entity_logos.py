from django.core.management.base import BaseCommand, CommandError

from game.models import League, Team, league_logo_upload_path, team_logo_upload_path
from game.services.local_logos import sync_entity_logo


MODEL_CONFIG = {
    "team": (Team, team_logo_upload_path),
    "league": (League, league_logo_upload_path),
}


class Command(BaseCommand):
    help = "Скачать локальные WebP-логотипы команд и лиг из сохранённых remote URL."

    def add_arguments(self, parser):
        parser.add_argument(
            "--model",
            choices=(*MODEL_CONFIG.keys(), "all"),
            default="all",
        )
        parser.add_argument("--limit", type=int)
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        limit = options["limit"]
        if limit is not None and limit <= 0:
            raise CommandError("--limit должен быть больше 0.")

        model_names = (
            MODEL_CONFIG.keys()
            if options["model"] == "all"
            else (options["model"],)
        )

        totals = {"scanned": 0, "downloaded": 0, "skipped": 0}
        for model_name in model_names:
            model, target_builder = MODEL_CONFIG[model_name]
            queryset = (
                model.objects.exclude(remote_logo_url="")
                .select_related("sport")
                .order_by("pk")
            )
            if limit is not None:
                queryset = queryset[:limit]

            for instance in queryset.iterator(chunk_size=200):
                totals["scanned"] += 1
                target_name = target_builder(instance, "")

                if options["dry_run"]:
                    self.stdout.write(
                        f"{model_name} #{instance.pk}: {target_name}"
                    )
                    totals["skipped"] += 1
                    continue

                downloaded = sync_entity_logo(
                    instance,
                    field_name="logo",
                    remote_url=instance.remote_logo_url,
                    target_name=target_name,
                    force=options["force"],
                )
                if downloaded:
                    totals["downloaded"] += 1
                else:
                    totals["skipped"] += 1

        self.stdout.write(
            self.style.SUCCESS(
                "Готово: "
                f"проверено {totals['scanned']}, "
                f"скачано {totals['downloaded']}, "
                f"пропущено {totals['skipped']}."
            )
        )
