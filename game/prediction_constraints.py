import json
from decimal import Decimal, InvalidOperation

from django.http import JsonResponse

from cabinet.models import User

from . import views
from .models import Match
from .services.match_timing import prediction_window_open


PREDICTION_STAKE_MIN_RUB = Decimal("100")
PREDICTION_STAKE_MAX_RUB = Decimal("1000000")
MIN_ALLOWED_COEFFICIENT = Decimal("1.01")


def create_coupon(request):
    """Validate public coupon limits and local kickoff time before writing."""
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

            timing_error = _validate_match_timing(payload)
            if timing_error:
                return JsonResponse({"ok": False, "error": timing_error}, status=409)

    return views.create_coupon(request)


def _validate_match_timing(payload: dict) -> str:
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        return ""

    match_ids = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            match_id = int(item.get("match_id"))
        except (TypeError, ValueError):
            continue
        if match_id > 0:
            match_ids.append(match_id)

    if not match_ids:
        return ""

    matches = Match.objects.filter(id__in=set(match_ids)).only(
        "id",
        "starts_at",
        "sync_scope",
        "raw_data",
        "home_team_id",
        "away_team_id",
    ).select_related("home_team", "away_team")

    for match in matches:
        if prediction_window_open(match):
            continue
        title = f"{match.home_team_name or 'Хозяева'} — {match.away_team_name or 'Гости'}"
        if not match.starts_at:
            return f"Для матча «{title}» не указано время начала. Ставка временно недоступна."
        return f"Матч «{title}» уже начался или скоро начнется. Добавить ставку больше нельзя."
    return ""


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
