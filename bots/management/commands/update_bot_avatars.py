import random

from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from bots.models import BotAccount
from cabinet.models import PresetAvatar, User


class Command(BaseCommand):
    help = "Заменить аватары всех ботов случайными активными PresetAvatar из админки."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Показать, сколько аватаров будет обновлено, не изменяя файлы и БД.",
        )
        parser.add_argument(
            "--only-missing",
            action="store_true",
            help="Назначать аватары только ботам без фотографии.",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=None,
            help="Число для повторяемого случайного распределения аватаров.",
        )

    def handle(self, *args, **options):
        presets = list(
            PresetAvatar.objects.filter(is_active=True)
            .exclude(image="")
            .order_by("sort_order", "pk")
        )
        if not presets:
            raise CommandError("Нет активных готовых аватаров с изображениями.")

        rng = random.Random(options["seed"])
        by_gender = {
            User.Gender.MALE: [
                avatar for avatar in presets
                if avatar.gender in (PresetAvatar.Gender.MALE, PresetAvatar.Gender.ALL)
            ],
            User.Gender.FEMALE: [
                avatar for avatar in presets
                if avatar.gender in (PresetAvatar.Gender.FEMALE, PresetAvatar.Gender.ALL)
            ],
        }
        updated = skipped = failed = 0
        bots = BotAccount.objects.select_related("user").order_by("pk")

        for bot in bots.iterator():
            user = bot.user
            if options["only_missing"] and user.avatar:
                skipped += 1
                continue

            # Все стандартные seed_bots персоны мужские; пустой gender трактуем как male.
            gender = user.gender if user.gender == User.Gender.FEMALE else User.Gender.MALE
            choices = by_gender[gender]
            if not choices:
                skipped += 1
                self.stderr.write(f"@{user.username}: нет готового аватара для пола {gender}.")
                continue

            preset = rng.choice(choices)
            if options["dry_run"]:
                updated += 1
                continue

            try:
                with preset.image.open("rb") as source:
                    filename = preset.image.name.rsplit("/", 1)[-1]
                    user.avatar.save(f"bot-preset-{preset.pk}-{filename}", File(source), save=False)
                    user.save(update_fields=["avatar"])
            except (OSError, ValueError) as exc:
                failed += 1
                self.stderr.write(f"@{user.username}: не удалось назначить аватар {preset.pk}: {exc}")
                continue

            updated += 1

        verb = "Можно обновить" if options["dry_run"] else "Обновлено"
        self.stdout.write(
            self.style.SUCCESS(
                f"{verb} аватаров: {updated}. Пропущено: {skipped}. Ошибок: {failed}."
            )
        )
