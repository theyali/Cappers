from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from achievements.services import sync_user_achievements


class Command(BaseCommand):
    help = "Синхронизировать достижения пользователей."

    def add_arguments(self, parser):
        target_group = parser.add_mutually_exclusive_group(required=True)
        target_group.add_argument(
            "--user-id",
            type=int,
            help="Пересчитать достижения только для одного пользователя.",
        )
        target_group.add_argument(
            "--all",
            action="store_true",
            help="Пересчитать достижения всех активных пользователей.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Показать результат без сохранения изменений.",
        )
        parser.add_argument(
            "--notify",
            action="store_true",
            help="Отправлять уведомления о новых достижениях.",
        )

    def handle(self, *args, **options):
        User = get_user_model()
        users = User.objects.filter(is_active=True).order_by("id")

        user_id = options.get("user_id")
        if user_id:
            users = users.filter(pk=user_id)

        dry_run = options["dry_run"]
        notify = options["notify"] and not dry_run
        users_count = 0
        awarded_count = 0
        errors_count = 0

        for user in users.iterator(chunk_size=500):
            try:
                with transaction.atomic():
                    awarded = sync_user_achievements(
                        user,
                        notify=notify,
                    )
                    if dry_run:
                        transaction.set_rollback(True)
            except Exception as exc:
                errors_count += 1
                self.stderr.write(
                    self.style.ERROR(
                        f"Ошибка для пользователя id={user.pk}: {exc}"
                    )
                )
                continue

            users_count += 1
            awarded_count += len(awarded)

        if user_id and not users_count and not errors_count:
            self.stdout.write(
                self.style.WARNING(
                    f"Активный пользователь с id={user_id} не найден."
                )
            )
            return

        prefix = "Dry run: " if dry_run else "Готово: "
        self.stdout.write(
            self.style.SUCCESS(
                prefix
                + f"пользователей пересчитано {users_count}, "
                f"новых достижений {awarded_count}, "
                f"ошибок {errors_count}."
            )
        )
