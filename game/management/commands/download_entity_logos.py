from concurrent.futures import ThreadPoolExecutor, as_completed

from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

from game.models import (
    Country,
    League,
    Sport,
    Team,
    country_logo_upload_path,
    league_logo_upload_path,
    sport_image_upload_path,
    team_logo_upload_path,
)
from game.services.local_logos import sync_entity_logo


MODEL_CONFIG = {
    "team": (Team, "logo", "remote_logo_url", team_logo_upload_path, True),
    "league": (League, "logo", "remote_logo_url", league_logo_upload_path, True),
    "country": (Country, "logo", "remote_logo_url", country_logo_upload_path, False),
    "sport": (Sport, "image", "remote_image_url", sport_image_upload_path, False),
}


class Command(BaseCommand):
    help = "Скачать локальные WebP-изображения спортивных сущностей из сохранённых remote URL."

    def add_arguments(self, parser):
        target_group = parser.add_mutually_exclusive_group(required=True)
        target_group.add_argument(
            "--model",
            choices=MODEL_CONFIG.keys(),
        )
        target_group.add_argument("--all", action="store_true")
        parser.add_argument("--limit", type=int)
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--workers",
            type=int,
            default=8,
            help="Количество параллельных потоков скачивания. По умолчанию 8.",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        if limit is not None and limit <= 0:
            raise CommandError("--limit должен быть больше 0.")
        workers = options["workers"]
        if workers <= 0:
            raise CommandError("--workers должен быть больше 0.")

        model_names = MODEL_CONFIG.keys() if options["all"] else (options["model"],)

        totals = {"scanned": 0, "downloaded": 0, "skipped": 0, "failed": 0}
        for model_name in model_names:
            model, field_name, remote_field, target_builder, needs_sport = MODEL_CONFIG[model_name]
            queryset = model.objects.exclude(**{remote_field: ""}).order_by("pk")
            if needs_sport:
                queryset = queryset.select_related("sport")
            if limit is not None:
                queryset = queryset[:limit]

            jobs = []
            for instance in queryset.iterator(chunk_size=200):
                totals["scanned"] += 1
                target_name = target_builder(instance, "")

                if options["dry_run"]:
                    self.stdout.write(
                        f"{model_name} #{instance.pk}: {target_name}"
                    )
                    totals["skipped"] += 1
                    continue

                jobs.append((instance, target_name))

            if workers == 1:
                for instance, target_name in jobs:
                    result = self._download_one(
                        instance,
                        field_name=field_name,
                        remote_field=remote_field,
                        target_name=target_name,
                        force=options["force"],
                    )
                    totals[result] += 1
                continue

            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = (
                    executor.submit(
                        self._download_one,
                        instance,
                        field_name=field_name,
                        remote_field=remote_field,
                        target_name=target_name,
                        force=options["force"],
                    )
                    for instance, target_name in jobs
                )
                for future in as_completed(futures):
                    totals[future.result()] += 1

        self.stdout.write(
            self.style.SUCCESS(
                "Готово: "
                f"scanned={totals['scanned']} "
                f"downloaded={totals['downloaded']} "
                f"skipped={totals['skipped']} "
                f"failed={totals['failed']}"
            )
        )

    @staticmethod
    def _download_one(
        instance,
        *,
        field_name: str,
        remote_field: str,
        target_name: str,
        force: bool,
    ) -> str:
        close_old_connections()
        try:
            field_file = getattr(instance, field_name)
            current_name = getattr(field_file, "name", "") or ""
            had_local_file = (
                bool(current_name and default_storage.exists(current_name))
                or default_storage.exists(target_name)
            )

            downloaded = sync_entity_logo(
                instance,
                field_name=field_name,
                remote_url=getattr(instance, remote_field),
                target_name=target_name,
                force=force,
            )
            if downloaded:
                return "downloaded"
            if had_local_file and not force:
                return "skipped"
            return "failed"
        finally:
            close_old_connections()
