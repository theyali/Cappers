from __future__ import annotations

import logging
import socket
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.files.storage import default_storage
from django.db import models
from PIL import UnidentifiedImageError

from cappers.media_webp import convert_image_content_to_webp

logger = logging.getLogger(__name__)

_ALLOWED_GENERIC_CONTENT_TYPES = {
    "application/octet-stream",
    "binary/octet-stream",
}


def _remote_image_bytes(remote_url: str) -> bytes:
    parsed = urlparse(remote_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Unsupported logo URL")

    timeout = max(int(getattr(settings, "LOCAL_LOGO_TIMEOUT", 8) or 8), 1)
    max_bytes = max(
        int(getattr(settings, "LOCAL_LOGO_MAX_BYTES", 2 * 1024 * 1024) or 0),
        1,
    )
    request = Request(remote_url, headers={"User-Agent": "Cappers/1.0"})

    with urlopen(request, timeout=timeout) as response:
        content_type = str(response.headers.get("Content-Type") or "")
        content_type = content_type.split(";", 1)[0].strip().lower()
        if (
            content_type
            and not content_type.startswith("image/")
            and content_type not in _ALLOWED_GENERIC_CONTENT_TYPES
        ):
            raise ValueError(f"Unsupported logo content type: {content_type}")

        content_length = response.headers.get("Content-Length")
        if content_length:
            try:
                content_length_value = int(content_length)
            except (TypeError, ValueError):
                content_length_value = None
            if content_length_value is not None and content_length_value > max_bytes:
                raise ValueError("Logo response is too large")

        payload = response.read(max_bytes + 1)

    if not payload:
        raise ValueError("Empty logo response")
    if len(payload) > max_bytes:
        raise ValueError("Logo response is too large")
    return payload


def sync_entity_logo(
    instance: models.Model,
    *,
    field_name: str,
    remote_url: str,
    target_name: str,
    force: bool = False,
) -> bool:
    if not bool(getattr(settings, "LOCAL_LOGO_DOWNLOAD_ENABLED", True)):
        return False

    remote_url = str(remote_url or "").strip()
    target_name = str(target_name or "").strip().lstrip("/")
    if not remote_url or not target_name or not instance.pk:
        return False

    field = instance._meta.get_field(field_name)
    if not isinstance(field, models.ImageField):
        logger.warning(
            "Local logo field is not ImageField model=%s field=%s",
            instance._meta.label_lower,
            field_name,
        )
        return False

    field_file = getattr(instance, field_name)
    current_name = getattr(field_file, "name", "") or ""
    if not force and current_name and default_storage.exists(current_name):
        return False
    if not force and default_storage.exists(target_name):
        instance.__class__._default_manager.filter(pk=instance.pk).update(
            **{field_name: target_name}
        )
        setattr(instance, field_name, target_name)
        return False

    try:
        payload = _remote_image_bytes(remote_url)
        quality = int(getattr(settings, "LOCAL_LOGO_WEBP_QUALITY", 82) or 82)
        output = convert_image_content_to_webp(BytesIO(payload), quality=quality)

        if default_storage.exists(target_name):
            default_storage.delete(target_name)
        saved_name = default_storage.save(target_name, output)

        instance.__class__._default_manager.filter(pk=instance.pk).update(
            **{field_name: saved_name}
        )
        setattr(instance, field_name, saved_name)
        return True
    except (
        HTTPError,
        URLError,
        socket.timeout,
        TimeoutError,
        OSError,
        UnidentifiedImageError,
        ValueError,
    ) as exc:
        logger.warning(
            "Logo download failed model=%s pk=%s url=%s error=%s",
            instance._meta.label_lower,
            instance.pk,
            remote_url,
            exc,
        )
        return False
