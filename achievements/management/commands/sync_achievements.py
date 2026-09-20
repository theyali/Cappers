from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Синхронизировать достижения пользователей."

    def handle(self, *args, **options):
        self.stdout.write("Синхронизация будет добавлена после создания моделей.")
