from django.contrib.auth.decorators import login_required
from django.http import JsonResponse

from pages.models import PageSEO


PROFILE_ROUTE_NAME = "cabinet:profile"
PROFILE_PATH = "/cabinet/profile/"


def _image_payload(field):
    if not field:
        return None
    try:
        return {
            "url": field.url,
            "width": field.width,
            "height": field.height,
        }
    except (AttributeError, FileNotFoundError, OSError, ValueError):
        return None


@login_required
def profile_promo_banner(request):
    page = None
    for exact_path in (PROFILE_PATH, ""):
        page = (
            PageSEO.objects.filter(
                route_name=PROFILE_ROUTE_NAME,
                exact_path=exact_path,
                is_active=True,
                promo_banners__is_active=True,
            )
            .prefetch_related("promo_banners")
            .distinct()
            .first()
        )
        if page is not None:
            break

    if page is None:
        return JsonResponse({"ok": True, "banner": None})

    banner = page.promo_banners.filter(is_active=True).first()
    if banner is None:
        return JsonResponse({"ok": True, "banner": None})

    image = _image_payload(banner.image)
    if image is None:
        return JsonResponse({"ok": True, "banner": None})

    return JsonResponse(
        {
            "ok": True,
            "banner": {
                "name": banner.name or "Промо",
                "url": banner.button_url,
                "image": image,
                "mobile_image": _image_payload(banner.mobile_image),
            },
        }
    )
