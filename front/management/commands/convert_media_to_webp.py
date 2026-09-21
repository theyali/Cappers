from __future__ import annotations

from pathlib import PurePosixPath

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError

from cappers.media_webp import (
    SKIPPED_EXTENSIONS,
    convert_instance_image_fields,
    image_field_names,
)


class Command(BaseCommand):
    help = "Convert existing ImageField media files to WebP."

    def add_arguments(self, parser):
        parser.add_argument(
            "--model",
            help="Optional model label, for example cabinet.User or back.Bookmaker.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Maximum number of objects to scan per model. 0 means no limit.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only print what would be converted.",
        )
        parser.add_argument(
            "--repair-missing",
            action="store_true",
            help=(
                "Repair database references when an old image is missing but "
                "the sibling .webp file already exists."
            ),
        )

    def handle(self, *args, **options):
        models = self._models(options.get("model"))
        limit = max(0, int(options.get("limit") or 0))
        dry_run = bool(options.get("dry_run"))
        repair_missing = bool(options.get("repair_missing"))

        scanned = 0
        converted = 0
        candidates = 0
        repaired = 0

        for model in models:
            image_fields = image_field_names(model)
            if not image_fields:
                continue

            queryset = model._default_manager.all().order_by(model._meta.pk.name)
            if limit:
                queryset = queryset[:limit]

            self.stdout.write(f"{model._meta.label}: scanning {', '.join(image_fields)}")
            for instance in queryset.iterator(chunk_size=100):
                scanned += 1
                if repair_missing:
                    repaired += self._repair_missing(instance, image_fields, dry_run)

                pending_fields = self._pending_fields(instance, image_fields)
                if not pending_fields:
                    continue

                candidates += len(pending_fields)
                if dry_run:
                    self.stdout.write(
                        f"  would convert pk={instance.pk}: {', '.join(pending_fields)}"
                    )
                    continue

                results = convert_instance_image_fields(instance)
                for result in results:
                    if result.converted:
                        converted += 1
                        self.stdout.write(
                            f"  converted pk={instance.pk}: "
                            f"{result.original_name} -> {result.name}"
                        )

        self.stdout.write(
            self.style.SUCCESS(
                "Done. "
                f"scanned={scanned} candidates={candidates} "
                f"converted={converted} repaired={repaired}"
            )
        )

    def _models(self, model_label: str | None):
        if not model_label:
            return apps.get_models()

        try:
            app_label, model_name = model_label.split(".", 1)
        except ValueError as exc:
            raise CommandError("--model must look like app_label.ModelName") from exc

        model = apps.get_model(app_label, model_name)
        if model is None:
            raise CommandError(f"Unknown model: {model_label}")
        return [model]

    def _pending_fields(self, instance, image_fields: tuple[str, ...]) -> list[str]:
        pending = []
        for field_name in image_fields:
            field_file = getattr(instance, field_name, None)
            name = getattr(field_file, "name", "") or ""
            if not name:
                continue
            if PurePosixPath(name).suffix.lower() in SKIPPED_EXTENSIONS:
                continue
            pending.append(field_name)
        return pending

    def _repair_missing(
        self,
        instance,
        image_fields: tuple[str, ...],
        dry_run: bool,
    ) -> int:
        updates = {}
        for field_name in image_fields:
            field_file = getattr(instance, field_name, None)
            name = getattr(field_file, "name", "") or ""
            if not name:
                continue
            path = PurePosixPath(name)
            if path.suffix.lower() in SKIPPED_EXTENSIONS:
                continue
            repaired_name = str(path.with_suffix(".webp"))
            storage = field_file.storage
            if storage.exists(name) or not storage.exists(repaired_name):
                continue
            updates[field_name] = repaired_name

        if not updates:
            return 0

        if dry_run:
            self.stdout.write(
                f"  would repair pk={instance.pk}: "
                + ", ".join(f"{field} -> {name}" for field, name in updates.items())
            )
            return len(updates)

        instance.__class__._default_manager.filter(pk=instance.pk).update(**updates)
        self.stdout.write(
            f"  repaired pk={instance.pk}: "
            + ", ".join(f"{field} -> {name}" for field, name in updates.items())
        )
        return len(updates)
