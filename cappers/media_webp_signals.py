from __future__ import annotations

from django.apps import apps
from django.db.models.signals import post_save

from .media_webp import (
    convert_instance_image_fields,
    image_field_names,
    media_webp_enabled,
    should_process_update,
)


def _convert_saved_images(sender, instance, raw=False, update_fields=None, **kwargs):
    if raw or not media_webp_enabled():
        return

    image_fields = image_field_names(sender)
    if not image_fields:
        return
    if not should_process_update(image_fields=image_fields, update_fields=update_fields):
        return

    convert_instance_image_fields(instance)


def register_media_webp_signals() -> None:
    for model in apps.get_models():
        image_fields = image_field_names(model)
        if not image_fields:
            continue
        post_save.connect(
            _convert_saved_images,
            sender=model,
            weak=False,
            dispatch_uid=f"media-webp:{model._meta.label_lower}",
        )
