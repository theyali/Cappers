import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from wallets.services import InsufficientCoins

from .models import VipPlan
from .vip import purchase_vip


def _request_plan_id(request):
    plan_id = request.POST.get("plan_id")
    if plan_id:
        return plan_id

    if request.content_type == "application/json":
        try:
            payload = json.loads(request.body or b"{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return payload.get("plan_id")
    return None


def _error_message(exc) -> str:
    if isinstance(exc, ValidationError):
        return exc.messages[0] if exc.messages else str(exc)
    return str(exc)


@login_required
@require_POST
def vip_purchase(request):
    plan_id = _request_plan_id(request)
    if not plan_id:
        return JsonResponse(
            {"ok": False, "error": "Не выбран VIP-тариф."},
            status=400,
        )

    plan = get_object_or_404(VipPlan, pk=plan_id, is_active=True)
    try:
        subscription, wallet = purchase_vip(request.user, plan)
    except (ValidationError, InsufficientCoins) as exc:
        return JsonResponse(
            {"ok": False, "error": _error_message(exc)},
            status=400,
        )

    return JsonResponse(
        {
            "ok": True,
            "subscription": {
                "id": subscription.pk,
                "plan_id": subscription.plan_id,
                "starts_at": subscription.starts_at.isoformat(),
                "ends_at": subscription.ends_at.isoformat(),
                "duration_days": subscription.duration_days,
                "source": subscription.source,
            },
            "coin_balance": wallet.balance,
        }
    )
