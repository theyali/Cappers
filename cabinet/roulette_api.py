import json
from json import JSONDecodeError

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.storage import default_storage
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from wallets.models import CapperBalance

from .roulette_history import RouletteSpin
from .roulette_models import RoulettePrize, RouletteSettings
from .roulette_rewards import UserRouletteRewardState
from .roulette_services import get_user_roulette_state
from .roulette_spin_service import (
    RouletteSpinError,
    get_available_roulette_prizes,
    spin_roulette,
)


RECENT_WINS_LIMIT = 10


def _iso(value):
    return value.isoformat() if value else None


def _error_response(code: str, message: str, *, status: int):
    return JsonResponse(
        {
            "ok": False,
            "code": code,
            "error": message,
        },
        status=status,
    )


def _validation_message(exc: ValidationError) -> str:
    messages = getattr(exc, "messages", None) or []
    return messages[0] if messages else str(exc)


def _spin_error_status(code: str) -> int:
    return {
        "missing_operation_id": 400,
        "invalid_operation_id": 400,
        "operation_id_conflict": 409,
        "no_spins": 409,
        "no_available_prizes": 409,
        "roulette_disabled": 503,
        "invalid_prize_weights": 503,
    }.get(code, 400)


def _current_prize_icon_url(request, prize) -> str:
    if not prize.icon:
        return ""
    try:
        return request.build_absolute_uri(prize.icon.url)
    except (ValueError, OSError):
        return ""


def _snapshot_icon_url(request, icon_name: str) -> str:
    if not icon_name:
        return ""
    try:
        return request.build_absolute_uri(default_storage.url(icon_name))
    except (ValueError, OSError):
        return ""


def _serialize_sector(request, prize) -> dict:
    # Deliberately do not expose `weight` or promo-code `reward_text` here.
    return {
        "prize_id": prize.pk,
        "sector_index": prize.sector_order,
        "title": prize.title,
        "short_text": prize.short_text,
        "icon_url": _current_prize_icon_url(request, prize),
        "reward_type": prize.reward_type,
        "visual_type": prize.reward_type,
        "reward_value": str(prize.reward_value),
    }


def _serialize_spin_prize(request, spin: RouletteSpin) -> dict:
    return {
        "prize_id": spin.prize_id,
        "sector_index": spin.prize_sector_order,
        "title": spin.prize_title,
        "short_text": spin.prize_short_text,
        "icon_url": _snapshot_icon_url(request, spin.prize_icon),
        "reward_type": spin.reward_type,
        "visual_type": spin.reward_type,
        "reward_value": str(spin.reward_value),
        "reward_text": spin.reward_text,
    }


def _serialize_reward_result(user, spin: RouletteSpin) -> dict:
    result = {"type": spin.reward_type}

    if spin.reward_type == RoulettePrize.RewardType.VIRTUAL_BALANCE:
        balance = (
            CapperBalance.objects.filter(user=user)
            .values_list("balance", flat=True)
            .first()
        )
        result["virtual_balance"] = str(balance) if balance is not None else None
        return result

    reward_state = UserRouletteRewardState.objects.filter(user=user).first()

    if spin.reward_type == RoulettePrize.RewardType.VIP_DAYS:
        result["vip_until"] = _iso(reward_state.vip_until) if reward_state else None
    elif spin.reward_type == RoulettePrize.RewardType.FREE_PREDICTIONS:
        result["free_predictions"] = reward_state.free_predictions if reward_state else 0
    elif spin.reward_type == RoulettePrize.RewardType.RATING_BOOST:
        result["rating_boost"] = str(reward_state.rating_boost) if reward_state else "0"
    elif spin.reward_type == RoulettePrize.RewardType.PROMO_CODE:
        result["promo_code"] = spin.reward_text

    return result


def _serialize_recent_win(request, spin: RouletteSpin) -> dict:
    return {
        "spin_id": spin.pk,
        "operation_id": str(spin.operation_id),
        "spun_at": _iso(spin.spun_at),
        "reward_status": spin.reward_status,
        "prize": _serialize_spin_prize(request, spin),
    }


@never_cache
@require_GET
def roulette_state(request):
    if not request.user.is_authenticated:
        return _error_response("authentication_required", "Требуется авторизация.", status=401)

    now = timezone.now()
    roulette_settings = RouletteSettings.load()
    state = get_user_roulette_state(request.user, now=now)
    sectors = get_available_roulette_prizes(user=request.user, now=now)
    recent_spins = (
        RouletteSpin.objects.filter(user=request.user)
        .select_related("prize")
        .order_by("-spun_at", "-id")[:RECENT_WINS_LIMIT]
    )

    return JsonResponse(
        {
            "ok": True,
            "enabled": roulette_settings.is_enabled,
            "server_time": _iso(now),
            "available_spins": state.available_spins,
            "next_spin_at": _iso(state.next_spin_at),
            "last_spin_at": _iso(state.last_spin_at),
            "total_spins": state.total_spins,
            "sectors": [_serialize_sector(request, prize) for prize in sectors],
            "recent_wins": [_serialize_recent_win(request, spin) for spin in recent_spins],
        }
    )


@never_cache
@require_POST
def roulette_spin(request):
    if not request.user.is_authenticated:
        return _error_response("authentication_required", "Требуется авторизация.", status=401)

    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, JSONDecodeError):
        return _error_response("invalid_json", "Некорректный JSON.", status=400)

    if not isinstance(payload, dict):
        return _error_response("invalid_json", "JSON должен быть объектом.", status=400)

    try:
        spin = spin_roulette(
            user=request.user,
            operation_id=payload.get("operation_id"),
        )
    except PermissionDenied as exc:
        return _error_response("authentication_required", str(exc), status=401)
    except RouletteSpinError as exc:
        code = getattr(exc, "code", None) or "spin_error"
        return _error_response(
            code,
            _validation_message(exc),
            status=_spin_error_status(code),
        )
    except ValidationError as exc:
        return _error_response(
            "reward_configuration_error",
            _validation_message(exc),
            status=422,
        )

    return JsonResponse(
        {
            "ok": True,
            "spin_id": spin.pk,
            "operation_id": str(spin.operation_id),
            "spun_at": _iso(spin.spun_at),
            "prize_id": spin.prize_id,
            "sector_index": spin.prize_sector_order,
            "prize": _serialize_spin_prize(request, spin),
            "reward_result": _serialize_reward_result(request.user, spin),
            "reward_status": spin.reward_status,
            "available_spins": spin.attempts_after,
            "next_spin_at": _iso(spin.next_spin_at),
            "server_time": _iso(timezone.now()),
        }
    )
