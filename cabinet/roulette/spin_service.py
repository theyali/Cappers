import uuid

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from .history import RouletteSpin
from .models import RoulettePrize, RouletteSettings
from .rewards import UserRouletteRewardState
from .state import UserRouletteState
from .errors import roulette_error
from .reward_service import issue_roulette_reward
from .selectors import (
    available_prizes as _available_prizes,
    choose_weighted_prize as _choose_weighted_prize,
)


__all__ = ("spin_roulette",)


def _normalize_operation_id(value) -> uuid.UUID:
    if not value:
        raise roulette_error(
            "Не передан ID операции прокрутки.",
            "missing_operation_id",
        )
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise roulette_error(
            "Некорректный ID операции прокрутки.",
            "invalid_operation_id",
        ) from exc


def _save_reward_state(reward_state: UserRouletteRewardState) -> None:
    reward_state.save(
        update_fields=(
            "vip_until",
            "free_predictions",
            "rating_boost",
            "updated_at",
        )
    )


def _existing_spin_for_operation(operation_id: uuid.UUID, user):
    spin = (
        RouletteSpin.objects.filter(operation_id=operation_id)
        .select_related("prize", "user")
        .first()
    )
    if spin is None:
        return None
    if spin.user_id != user.pk:
        raise roulette_error(
            "Этот ID операции уже использован другим пользователем.",
            "operation_id_conflict",
        )
    return spin


def spin_roulette(user, operation_id, now=None) -> RouletteSpin:
    """Perform one server-authoritative roulette spin."""
    if not getattr(user, "is_authenticated", False):
        raise PermissionDenied("Войдите, чтобы крутить рулетку.")

    operation_id = _normalize_operation_id(operation_id)
    now = now or timezone.now()

    existing = _existing_spin_for_operation(operation_id, user)
    if existing is not None:
        return existing

    with transaction.atomic():
        locked_user = user.__class__.objects.select_for_update().get(pk=user.pk)

        existing = _existing_spin_for_operation(operation_id, locked_user)
        if existing is not None:
            return existing

        roulette_settings = RouletteSettings.load()
        if not roulette_settings.is_enabled:
            raise roulette_error(
                "Рулетка временно отключена.",
                "roulette_disabled",
            )

        state, _ = UserRouletteState.objects.get_or_create(user=locked_user)
        state = UserRouletteState.objects.select_for_update().get(pk=state.pk)
        state.refresh_daily_spins(
            now=now,
            roulette_settings=roulette_settings,
            save=False,
        )
        if state.available_spins <= 0:
            raise roulette_error("Нет доступных попыток.", "no_spins")

        reward_state, _ = UserRouletteRewardState.objects.get_or_create(user=locked_user)
        reward_state = UserRouletteRewardState.objects.select_for_update().get(
            pk=reward_state.pk
        )

        prizes = _available_prizes(
            user=locked_user,
            reward_state=reward_state,
            roulette_settings=roulette_settings,
            now=now,
            lock=True,
        )
        if not prizes:
            raise roulette_error(
                "Сейчас нет доступных призов для этой рулетки.",
                "no_available_prizes",
            )

        prize = _choose_weighted_prize(prizes)
        attempts_before = state.available_spins

        state.consume_spin(
            now=now,
            roulette_settings=roulette_settings,
            save=False,
        )

        spin = RouletteSpin.create_for_spin(
            user=locked_user,
            prize=prize,
            attempts_before=attempts_before,
            attempts_after=state.available_spins,
            next_spin_at=state.next_spin_at,
            spun_at=now,
            operation_id=operation_id,
        )

        issue_roulette_reward(
            spin=spin,
            prize=prize,
            user=locked_user,
            state=state,
            reward_state=reward_state,
            now=now,
        )

        state.save(
            update_fields=(
                "available_spins",
                "next_spin_at",
                "last_spin_at",
                "total_spins",
                "last_daily_grant_at",
                "updated_at",
            )
        )
        _save_reward_state(reward_state)

        spin.attempts_after = state.available_spins
        if prize.reward_type == RoulettePrize.RewardType.NOTHING:
            spin.reward_status = RouletteSpin.RewardStatus.NOT_REQUIRED
            spin.issued_at = None
        else:
            spin.reward_status = RouletteSpin.RewardStatus.ISSUED
            spin.issued_at = now
        spin.issue_error = ""
        spin.save(
            update_fields=(
                "attempts_after",
                "reward_status",
                "issued_at",
                "issue_error",
                "updated_at",
            )
        )

        return spin
