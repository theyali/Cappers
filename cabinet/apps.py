from django.apps import AppConfig


class CabinetConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "cabinet"
    verbose_name = "Личный кабинет"

    def ready(self) -> None:
        from . import signals  # noqa: F401
