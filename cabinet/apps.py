from django.apps import AppConfig


class CabinetConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "cabinet"
    verbose_name = "Личный кабинет"

    def ready(self) -> None:
        from . import presence  # noqa: F401
        from .comments import models as comment_models  # noqa: F401
        from .comments import admin as comment_admin  # noqa: F401
        from .roulette import history  # noqa: F401
        from .roulette import models as roulette_models  # noqa: F401
        from .roulette import rewards  # noqa: F401
        from .roulette import state  # noqa: F401
        from . import signals  # noqa: F401
