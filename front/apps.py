from django.apps import AppConfig


class FrontConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "front"

    def ready(self) -> None:
        from cappers.media_webp_signals import register_media_webp_signals

        register_media_webp_signals()
        from . import metric_models  # noqa: F401
        from . import metric_signals  # noqa: F401
