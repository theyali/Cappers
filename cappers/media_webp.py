from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Iterable

from django.apps import apps
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import models
from PIL import Image, ImageOps, UnidentifiedImageError

try:
    import cairosvg
except ImportError:  # pragma: no cover - exercised when optional dependency is absent.
    cairosvg = None


SKIPPED_EXTENSIONS = {".webp", ".svg", ".gif", ".avif"}


@dataclass(frozen=True)
class WebPConversionResult:
    original_name: str
    name: str
    converted: bool
    reason: str = ""


def media_webp_enabled() -> bool:
    return bool(getattr(settings, "MEDIA_WEBP_CONVERSION_ENABLED", True))


def image_field_names(model: type[models.Model]) -> tuple[str, ...]:
    return tuple(
        field.name
        for field in model._meta.fields
        if isinstance(field, models.ImageField)
    )


def should_process_update(
    *,
    image_fields: Iterable[str],
    update_fields: Iterable[str] | None,
) -> bool:
    if update_fields is None:
        return True
    return bool(set(image_fields) & set(update_fields))


def _target_name(original_name: str) -> str:
    path = PurePosixPath(original_name)
    return str(path.with_suffix(".webp"))


def _delete_original_after_conversion(storage, original_name: str, converted_name: str) -> None:
    if not bool(getattr(settings, "MEDIA_WEBP_DELETE_ORIGINAL", True)):
        return
    if not original_name or original_name == converted_name:
        return

    try:
        if storage.exists(original_name):
            storage.delete(original_name)
    except OSError:
        pass


def update_image_references(original_name: str, converted_name: str) -> int:
    if not original_name or not converted_name or original_name == converted_name:
        return 0

    updates_count = 0
    for model in apps.get_models():
        for field_name in image_field_names(model):
            updates_count += model._default_manager.filter(
                **{field_name: original_name}
            ).update(**{field_name: converted_name})
    return updates_count


def _normalized_image(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image)
    if image.mode in {"RGBA", "LA"} or (
        image.mode == "P" and "transparency" in image.info
    ):
        return image.convert("RGBA")
    return image.convert("RGB")


def _resize_image(image: Image.Image) -> Image.Image:
    max_width = int(getattr(settings, "MEDIA_WEBP_MAX_WIDTH", 1920) or 0)
    max_height = int(getattr(settings, "MEDIA_WEBP_MAX_HEIGHT", 1920) or 0)
    if max_width <= 0 or max_height <= 0:
        return image
    if image.width <= max_width and image.height <= max_height:
        return image

    image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
    return image


def _source_bytes(source) -> bytes:
    position = None
    if hasattr(source, "tell"):
        try:
            position = source.tell()
        except OSError:
            position = None

    payload = source.read()

    if position is not None and hasattr(source, "seek"):
        try:
            source.seek(position)
        except OSError:
            pass
    return payload


def _looks_like_svg(payload: bytes) -> bool:
    prefix = payload[:512].lstrip().lower()
    return prefix.startswith(b"<svg") or b"<svg" in prefix


def _svg_to_png_bytes(payload: bytes) -> bytes:
    if cairosvg is None:
        raise ValueError("SVG conversion requires CairoSVG")
    try:
        return cairosvg.svg2png(bytestring=payload, output_width=256, output_height=256)
    except Exception as exc:
        raise ValueError(f"SVG conversion failed: {exc}") from exc


def convert_image_content_to_webp(source, *, quality: int | None = None) -> ContentFile:
    if quality is None:
        quality = int(getattr(settings, "MEDIA_WEBP_QUALITY", 82) or 82)
    quality = min(100, max(1, int(quality)))

    payload = _source_bytes(source)
    if _looks_like_svg(payload):
        payload = _svg_to_png_bytes(payload)

    with Image.open(ContentFile(payload)) as opened:
        image = _resize_image(_normalized_image(opened))
        output = ContentFile(b"")
        image.save(
            output,
            format="WEBP",
            quality=quality,
            method=6,
        )

    output.seek(0)
    return output


def convert_field_file_to_webp(field_file) -> WebPConversionResult:
    if not media_webp_enabled():
        return WebPConversionResult(
            original_name=getattr(field_file, "name", "") or "",
            name=getattr(field_file, "name", "") or "",
            converted=False,
            reason="disabled",
        )

    original_name = getattr(field_file, "name", "") or ""
    if not original_name:
        return WebPConversionResult("", "", False, "empty")

    suffix = PurePosixPath(original_name).suffix.lower()
    if suffix in SKIPPED_EXTENSIONS:
        return WebPConversionResult(original_name, original_name, False, "skipped")

    storage = field_file.storage
    if not storage.exists(original_name):
        return WebPConversionResult(original_name, original_name, False, "missing")

    target_name = _target_name(original_name)

    try:
        with storage.open(original_name, "rb") as source:
            output = convert_image_content_to_webp(source)
    except (OSError, UnidentifiedImageError, ValueError) as exc:
        return WebPConversionResult(
            original_name,
            original_name,
            False,
            f"invalid:{exc.__class__.__name__}",
        )

    output.seek(0)
    saved_name = storage.save(target_name, output)
    return WebPConversionResult(original_name, saved_name, True)


def convert_instance_image_fields(instance: models.Model) -> list[WebPConversionResult]:
    results = []
    updates = {}
    for field_name in image_field_names(instance.__class__):
        field_file = getattr(instance, field_name, None)
        result = convert_field_file_to_webp(field_file)
        results.append(result)
        if result.converted:
            update_image_references(result.original_name, result.name)
            _delete_original_after_conversion(
                field_file.storage,
                result.original_name,
                result.name,
            )
            setattr(instance, field_name, result.name)
            updates[field_name] = result.name

    if updates and instance.pk:
        instance.__class__._default_manager.filter(pk=instance.pk).update(**updates)
    return results
