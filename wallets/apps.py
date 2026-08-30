from django.apps import AppConfig


class WalletsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "wallets"
    verbose_name = "Финансы"

    def ready(self) -> None:
        from . import signals  # noqa: F401
