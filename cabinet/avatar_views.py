from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from PIL import Image, UnidentifiedImageError

from .models import AnalystProfile, User


ALLOWED_AVATAR_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_AVATAR_SIZE = 5 * 1024 * 1024


def _current_avatar(user: User):
    if user.is_analyst:
        try:
            profile = user.analyst_profile
        except AnalystProfile.DoesNotExist:
            profile = None
        if profile and profile.avatar:
            return profile.avatar
    return user.avatar if user.avatar else None


def _avatar_url(user: User) -> str:
    avatar = _current_avatar(user)
    return avatar.url if avatar else ""


def _validate_avatar(upload):
    if not upload:
        return "Выберите изображение."
    if upload.size > MAX_AVATAR_SIZE:
        return "Максимальный размер файла — 5 МБ."
    content_type = getattr(upload, "content_type", "")
    if content_type and content_type not in ALLOWED_AVATAR_TYPES:
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
    error = _validate_avatar(upload)
    if error:
        return JsonResponse({"ok": False, "error": error}, status=400)

    if request.user.is_analyst:
        profile, _ = AnalystProfile.objects.get_or_create(user=request.user)
        previous_name = profile.avatar.name if profile.avatar else ""
        storage = profile.avatar.storage if profile.avatar else None
        profile.avatar = upload
        profile.save(update_fields=["avatar", "updated_at"])
        avatar = profile.avatar
    else:
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
