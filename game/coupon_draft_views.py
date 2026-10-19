from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET
from django.views.decorators.cache import never_cache

from cabinet.paid_predictions import profile_paid_predictions_enabled
from game.services.coupon_draft import active_draft_coupon, serialize_draft_coupon
from game.services.prediction_editor import build_editor_positions


@login_required
@require_GET
@never_cache
def coupon_draft_state(request):
    if not request.user.is_analyst:
        raise PermissionDenied
    coupon = active_draft_coupon(request.user)
    payload = {"ok": True, "draft": serialize_draft_coupon(coupon) if coupon else None,
               "paid_available": request.user.is_vip and profile_paid_predictions_enabled(request.user)}
    if request.GET.get("editor") == "1":
        predictions, timing, _blocked = build_editor_positions(coupon)
        payload["editor_html"] = render_to_string("game/includes/_rich_prediction_coupon_items.html", {
            "predictions": predictions, "coupon": coupon, "is_published": False,
        }, request=request)
        payload["timings"] = timing
    return JsonResponse(payload)
