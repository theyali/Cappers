from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from PIL import Image, UnidentifiedImageError

from .models import User


ALLOWED_PROFILE_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_PROFILE_IMAGE_SIZE = 5 * 1024 * 1024


def _current_avatar(user: User):
    return user.avatar if user.avatar else None


def _avatar_url(user: User) -> str:
    avatar = _current_avatar(user)
    return avatar.url if avatar else ""


def _validate_profile_image(upload):
    if not upload:
        return "Выберите изображение."
    if upload.size > MAX_PROFILE_IMAGE_SIZE:
        return "Максимальный размер файла — 5 МБ."
    content_type = getattr(upload, "content_type", "")
    if content_type and content_type not in ALLOWED_PROFILE_IMAGE_TYPES:
        return "Разрешены JPG, PNG и WebP."

    try:
        Image.open(upload).verify()
    except (UnidentifiedImageError, OSError, ValueError):
        return "Файл не является корректным изображением."
    finally:
        try:
            upload.seek(0)
        except (AttributeError, OSError):
            pass
    return ""


@login_required
@require_http_methods(["GET", "POST"])
def avatar(request):
    if request.method == "GET":
        return JsonResponse({"ok": True, "avatar_url": _avatar_url(request.user)})

    upload = request.FILES.get("avatar")
    error = _validate_profile_image(upload)
    if error:
        return JsonResponse({"ok": False, "error": error}, status=400)

    previous_name = request.user.avatar.name if request.user.avatar else ""
    storage = request.user.avatar.storage if request.user.avatar else None
    request.user.avatar = upload
    request.user.save(update_fields=["avatar"])
    avatar = request.user.avatar

    if previous_name and storage and previous_name != avatar.name and storage.exists(previous_name):
        storage.delete(previous_name)

    return JsonResponse(
        {
            "ok": True,
            "avatar_url": avatar.url,
            "message": "Аватар обновлён.",
        }
    )
