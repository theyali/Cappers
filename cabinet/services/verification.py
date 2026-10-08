from django.db import transaction
from django.utils import timezone

from cabinet.models import AnalystProfile
from game.models import PredictionCoupon

# Published coupons a capper needs before asking for the checkmark.
MIN_PUBLISHED_COUPONS = 5


def verification_state(user, analyst_profile: AnalystProfile) -> dict:
    """What the capper still needs for the checkmark and whether the button shows.

    The checkmark is granted on request. If an admin removes it later, the
    request date stays and the capper cannot ask again until an admin clears it.
    """
    published_coupons = PredictionCoupon.objects.filter(
        author=user,
        published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
    ).count()
    items = [
        {
            "label": f"Опубликовать {MIN_PUBLISHED_COUPONS} купонов (сейчас {min(published_coupons, MIN_PUBLISHED_COUPONS)})",
            "done": published_coupons >= MIN_PUBLISHED_COUPONS,
        },
        {"label": "Специализация", "done": bool(analyst_profile.specialization.strip())},
        {"label": "Отображаемое имя", "done": bool(analyst_profile.display_name.strip())},
        {"label": "Имя", "done": bool(user.first_name.strip())},
        {"label": "Фамилия", "done": bool(user.last_name.strip())},
        {"label": "Фото профиля", "done": bool(user.avatar)},
        {"label": "О себе", "done": bool(analyst_profile.bio.strip())},
        {"label": "Хотя бы одна соцсеть", "done": bool(analyst_profile.social_links)},
        {"label": "Любимые виды спорта", "done": user.sport_preferences.exists()},
    ]
    if analyst_profile.is_verified:
        status = "verified"
    elif analyst_profile.verification_requested_at:
        status = "revoked"
    elif all(item["done"] for item in items):
        status = "ready"
    else:
        status = "incomplete"
    return {"status": status, "items": items, "can_request": status == "ready"}


def grant_verification(user, analyst_profile: AnalystProfile) -> tuple[bool, str]:
    """Give the checkmark if the capper meets every requirement now."""
    with transaction.atomic():
        analyst_profile = AnalystProfile.objects.select_for_update().get(pk=analyst_profile.pk)
        state = verification_state(user, analyst_profile)
        if state["status"] == "verified":
            return True, "Галочка уже есть."
        if state["status"] == "revoked":
            return False, "Галочку снял модератор. Если это ошибка, напишите в поддержку."
        if not state["can_request"]:
            missing = ", ".join(item["label"] for item in state["items"] if not item["done"])
            return False, f"Для галочки нужно: {missing}."
        analyst_profile.is_verified = True
        analyst_profile.verification_requested_at = timezone.now()
        analyst_profile.save(update_fields=["is_verified", "verification_requested_at", "updated_at"])
    return True, "Готово: галочка появилась рядом с вашим именем."
