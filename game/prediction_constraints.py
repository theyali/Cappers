import json
from decimal import Decimal, InvalidOperation

from django.http import JsonResponse

from cabinet.models import User

from . import views


PREDICTION_STAKE_MIN_RUB = Decimal("100")
PREDICTION_STAKE_MAX_RUB = Decimal("1000000")
MIN_ALLOWED_COEFFICIENT = Decimal("1.01")


def create_coupon(request):
    """Validate public coupon limits before delegating to the canonical writer."""
    if (
        request.method == "POST"
        and request.user.is_authenticated
        and request.user.role == User.Role.ANALYST
    ):
        try:
            payload = json.loads(request.body.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = None

        if isinstance(payload, dict):
            error = _validate_payload_limits(payload)
            if error:
                return JsonResponse({"ok": False, "error": error}, status=400)

    return views.create_coupon(request)


def _validate_payload_limits(payload: dict) -> str:
    autosave = bool(payload.get("autosave"))
    raw_stake = str(payload.get("stake") or "").replace(",", ".").strip()
    if raw_stake and not autosave:
        try:
            stake = Decimal(raw_stake)
        except (InvalidOperation, ValueError):
            stake = None
        if stake is not None:
            if stake < PREDICTION_STAKE_MIN_RUB:
                return f"Минимальная сумма прогноза — {int(PREDICTION_STAKE_MIN_RUB)} ₽."
            if stake > PREDICTION_STAKE_MAX_RUB:
                return f"Максимальная сумма прогноза — {int(PREDICTION_STAKE_MAX_RUB):,} ₽.".replace(",", " ")

    items = payload.get("items")
    if not isinstance(items, list):
        return ""

    for item in items:
        if not isinstance(item, dict):
            continue
        raw_coefficient = str(item.get("coefficient") or "").replace(",", ".").strip()
        if not raw_coefficient:
            continue
        try:
            coefficient = Decimal(raw_coefficient)
        except (InvalidOperation, ValueError):
            continue
        if coefficient < MIN_ALLOWED_COEFFICIENT:
            return "Коэффициент 1.00 нельзя добавлять в прогноз. Выберите доступный коэффициент выше 1.00."

    return ""
