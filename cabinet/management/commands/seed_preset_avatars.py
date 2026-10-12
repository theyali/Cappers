from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from cabinet.models import PresetAvatar


DEFAULT_SEED_DIR = settings.BASE_DIR / "seed_data" / "avatars" / "png-256"


def _avatar_title(path: Path) -> str:
    gender, number = path.stem.split("-", 1)
    prefix = "Мужской" if gender == "male" else "Женский"
    return f"{prefix} аватар {number}"


def _avatar_gender(path: Path) -> str:
    if path.stem.startswith("male-"):
        return PresetAvatar.Gender.MALE
    if path.stem.startswith("female-"):
        return PresetAvatar.Gender.FEMALE
    raise CommandError(f"Неизвестный формат имени файла: {path.name}")


def _avatar_sort_order(path: Path) -> int:
    gender, number = path.stem.split("-", 1)
    offset = 0 if gender == "male" else 100
    return offset + int(number)


class Command(BaseCommand):
    help = "Заполнить готовые аватары из seed_data/avatars/png-256."

    def add_arguments(self, parser):
        parser.add_argument(
            "--seed-dir",
            default=str(DEFAULT_SEED_DIR),
            help="Папка с PNG 256x256 аватарами.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Перезаписать изображения у существующих аватаров.",
        )

    def handle(self, *args, **options):
        seed_dir = Path(options["seed_dir"]).expanduser().resolve()
        if not seed_dir.is_dir():
            raise CommandError(f"Папка с аватарами не найдена: {seed_dir}")

        avatar_files = sorted(seed_dir.glob("*.png"))
        if not avatar_files:
            raise CommandError(f"PNG-файлы не найдены: {seed_dir}")

        created_count = 0
        updated_count = 0
        skipped_count = 0
        force = options["force"]

        with transaction.atomic():
            for avatar_path in avatar_files:
                title = _avatar_title(avatar_path)
                gender = _avatar_gender(avatar_path)
                sort_order = _avatar_sort_order(avatar_path)

                avatar, created = PresetAvatar.objects.get_or_create(
                    title=title,
                    defaults={
                        "gender": gender,
                        "is_active": True,
                        "sort_order": sort_order,
                    },
                )

                changed = created
                if avatar.gender != gender:
                    avatar.gender = gender
                    changed = True
                if avatar.sort_order != sort_order:
                    avatar.sort_order = sort_order
                    changed = True
                if not avatar.is_active:
                    avatar.is_active = True
                    changed = True

                if created or force or not avatar.image:
                    if avatar.image:
                        avatar.image.delete(save=False)
                    with avatar_path.open("rb") as source_file:
                        avatar.image.save(avatar_path.name, File(source_file), save=False)
                    changed = True

                if changed:
                    avatar.save()
                    if created:
                        created_count += 1
                    else:
                        updated_count += 1
                else:
                    skipped_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                "Готово: "
                f"создано {created_count}, "
                f"обновлено {updated_count}, "
                f"пропущено {skipped_count}."
            )
        )
