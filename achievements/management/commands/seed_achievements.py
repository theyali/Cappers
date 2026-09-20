from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Создать базовые достижения."

    def handle(self, *args, **options):
        self.stdout.write("Достижения будут добавлены после создания моделей.")
