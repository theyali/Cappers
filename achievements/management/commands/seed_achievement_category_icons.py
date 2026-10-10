from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from achievements.models import AchievementCategory


DEFAULT_SEED_DIR = settings.BASE_DIR / "seed_data" / "achievments"

CATEGORY_ICON_FILES = {
    "predictions": "comments.png",
    "wins": "top10.png",
    "roi": "roi.png",
    "audience": "subscribers.png",
    "streaks": "streak.png",
    "status": "verification.png",
    "referrals": "referrals.png",
    "activity": "likes.png",
}


class Command(BaseCommand):
    help = "Заполнить иконки категорий достижений из seed_data/achievments."

    def add_arguments(self, parser):
        parser.add_argument(
            "--seed-dir",
            default=str(DEFAULT_SEED_DIR),
            help="Папка с png-иконками достижений.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Перезаписать уже заданные иконки категорий.",
        )

    def handle(self, *args, **options):
        seed_dir = Path(options["seed_dir"])
        if not seed_dir.exists():
            raise CommandError(f"Папка с иконками не найдена: {seed_dir}")

        force = options["force"]
        updated_count = 0
        skipped_count = 0
        missing_categories = []
        missing_files = []

        for slug, filename in CATEGORY_ICON_FILES.items():
            category = AchievementCategory.objects.filter(slug=slug).first()
            if category is None:
                missing_categories.append(slug)
                continue

            if category.icon and not force:
                skipped_count += 1
                continue

            source_path = seed_dir / filename
            if not source_path.exists():
                missing_files.append(str(source_path))
                continue

            if category.icon:
                category.icon.delete(save=False)
            with source_path.open("rb") as source_file:
                category.icon.save(
                    filename,
                    File(source_file),
                    save=True,
                )
            updated_count += 1

        if missing_categories:
            self.stdout.write(
                self.style.WARNING(
                    "Категории не найдены: "
                    + ", ".join(sorted(missing_categories))
                )
            )
        if missing_files:
            self.stdout.write(
                self.style.WARNING(
                    "Файлы не найдены: "
                    + ", ".join(sorted(missing_files))
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Готово: "
                f"иконок обновлено {updated_count}, "
                f"пропущено {skipped_count}."
            )
        )
