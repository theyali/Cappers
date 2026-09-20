from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from achievements.services import sync_user_achievements


class Command(BaseCommand):
    help = "Синхронизировать достижения пользователей."

    def add_arguments(self, parser):
        parser.add_argument(
            "--user-id",
            type=int,
            help="Пересчитать достижения только для одного пользователя.",
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

        users_count = 0
        awarded_count = 0

        for user in users.iterator():
            awarded_count += len(
                sync_user_achievements(
                    user,
                    notify=options["notify"],
                )
            )
            users_count += 1

        if user_id and not users_count:
            self.stdout.write(
                self.style.WARNING(
                    f"Активный пользователь с id={user_id} не найден."
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                "Готово: "
                f"пользователей пересчитано {users_count}, "
                f"новых достижений выдано {awarded_count}."
            )
        )
