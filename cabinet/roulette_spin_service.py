import secrets
import uuid
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from front.models import PredictionFavorite, PredictionLike
from wallets.services import top_up_virtual_balance

from .roulette_history import RouletteSpin
from .roulette_models import RoulettePrize, RouletteSettings
from .roulette_rewards import UserRouletteRewardState
from .roulette_state import UserRouletteState, roulette_daily_window


class RouletteSpinError(ValidationError):
    pass


def _error(message: str, code: str) -> RouletteSpinError:
    return RouletteSpinError(message, code=code)


def _normalize_operation_id(value) -> uuid.UUID:
    if not value:
        raise _error("Не передан ID операции прокрутки.", "missing_operation_id")
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise _error("Некорректный ID операции прокрутки.", "invalid_operation_id") from exc


def _activity_count(user) -> int:
    return (
        PredictionLike.objects.filter(user=user).count()
        + PredictionFavorite.objects.filter(user=user).count()
    )


def _has_active_vip(user, reward_state: UserRouletteRewardState, now) -> bool:
    if reward_state.vip_until and reward_state.vip_until > now:
        return True
    analyst_profile = getattr(user, "analyst_profile", None)
    return bool(analyst_profile and analyst_profile.is_vip)


def _condition_matches(condition, *, user, reward_state, now, activity_count) -> bool:
    condition_type = condition.condition_type
    threshold = condition.threshold or 0

    if condition_type == condition.ConditionType.ALL_USERS:
        return True
    if condition_type == condition.ConditionType.READERS_ONLY:
        return getattr(user, "role", "") == "reader"
    if condition_type == condition.ConditionType.ANALYSTS_ONLY:
        return getattr(user, "role", "") == "analyst"
    if condition_type == condition.ConditionType.WITHOUT_VIP:
        return not _has_active_vip(user, reward_state, now)
    if condition_type == condition.ConditionType.MIN_ACCOUNT_AGE_DAYS:
        joined_at = getattr(user, "date_joined", None)
        if not joined_at:
            return False
        return (now - joined_at).days >= threshold
    if condition_type == condition.ConditionType.MIN_ACTIVITY_COUNT:
        return activity_count >= threshold
    return False


def _prize_matches_conditions(prize, *, user, reward_state, now, activity_count) -> bool:
    conditions = [condition for condition in prize.conditions.all() if condition.is_active]
    if not conditions:
        return True

    results = [
        _condition_matches(
            condition,
            user=user,
            reward_state=reward_state,
            now=now,
            activity_count=activity_count,
        )
        for condition in conditions
    ]
    if prize.condition_logic == RoulettePrize.ConditionLogic.ANY:
        return any(results)
    return all(results)


def _prize_within_limits(prize, *, user, window_start, next_reset) -> bool:
    spins = RouletteSpin.objects.filter(prize=prize)

    if prize.total_award_limit is not None and spins.count() >= prize.total_award_limit:
        return False
    if (
        prize.per_user_award_limit is not None
        and spins.filter(user=user).count() >= prize.per_user_award_limit
    ):
        return False
    if (
        prize.daily_award_limit is not None
        and spins.filter(spun_at__gte=window_start, spun_at__lt=next_reset).count()
        >= prize.daily_award_limit
    ):
        return False
    return True


def _available_prizes(*, user, reward_state, roulette_settings, now):
    window_start, next_reset = roulette_daily_window(roulette_settings, now)
    activity_count = _activity_count(user)

    prizes = list(
        RoulettePrize.objects.select_for_update()
        .filter(is_active=True)
        .filter(Q(active_from__isnull=True) | Q(active_from__lte=now))
        .filter(Q(active_until__isnull=True) | Q(active_until__gt=now))
        .prefetch_related("conditions")
        .order_by("sector_order", "id")
    )

    return [
        prize
        for prize in prizes
        if _prize_within_limits(
            prize,
            user=user,
            window_start=window_start,
            next_reset=next_reset,
        )
        and _prize_matches_conditions(
            prize,
            user=user,
            reward_state=reward_state,
            now=now,
            activity_count=activity_count,
        )
    ]


def _choose_weighted_prize(prizes):
    total_weight = sum(int(prize.weight) for prize in prizes)
    if total_weight <= 0:
        raise _error("Для рулетки не настроены корректные веса призов.", "invalid_prize_weights")

    ticket = secrets.randbelow(total_weight)
    cursor = 0
    for prize in prizes:
        cursor += int(prize.weight)
        if ticket < cursor:
            return prize
    return prizes[-1]


def _issue_reward(*, spin, prize, user, state, reward_state, now) -> None:
    reward_type = prize.reward_type
    reward_value = Decimal(str(prize.reward_value or 0))

    if reward_type == RoulettePrize.RewardType.NOTHING:
        return

    if reward_type == RoulettePrize.RewardType.VIRTUAL_BALANCE:
        top_up_virtual_balance(
            user,
            reward_value,
            note=f"Приз рулетки: {prize.title} · операция {spin.operation_id}",
        )
        return

    if reward_type == RoulettePrize.RewardType.VIP_DAYS:
        reward_state.grant_vip_days(int(reward_value), now=now, save=False)
        return

    if reward_type == RoulettePrize.RewardType.FREE_PREDICTIONS:
        reward_state.grant_free_predictions(int(reward_value), save=False)
        return

    if reward_type == RoulettePrize.RewardType.PROMO_CODE:
        if not prize.reward_text.strip():
            raise _error("У выпавшего приза не настроен промокод.", "invalid_promo_reward")
        return

    if reward_type == RoulettePrize.RewardType.RATING_BOOST:
        reward_state.grant_rating_boost(reward_value, save=False)
        return

    if reward_type == RoulettePrize.RewardType.EXTRA_SPIN:
        state.grant_spins(int(reward_value), save=False)
        return

    raise _error("Неизвестный тип награды рулетки.", "unsupported_reward_type")


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
        raise _error("Этот ID операции уже использован другим пользователем.", "operation_id_conflict")
    return spin


def spin_roulette(*, user, operation_id, now=None) -> RouletteSpin:
    """Perform one server-authoritative roulette spin.

    `operation_id` is the idempotency key. The API/client must reuse the same UUID
    while retrying the same user action. Prize choice never comes from the client.
    """
    if not getattr(user, "is_authenticated", False):
        raise PermissionDenied("Войдите, чтобы крутить рулетку.")

    operation_id = _normalize_operation_id(operation_id)
    now = now or timezone.now()

    existing = _existing_spin_for_operation(operation_id, user)
    if existing is not None:
        return existing

    with transaction.atomic():
        # Lock the user first. This serializes first-time state creation and also
        # makes two concurrent spin requests for the same user execute one-by-one.
        locked_user = user.__class__.objects.select_for_update().get(pk=user.pk)

        existing = _existing_spin_for_operation(operation_id, locked_user)
        if existing is not None:
            return existing

        roulette_settings = RouletteSettings.load()
        if not roulette_settings.is_enabled:
            raise _error("Рулетка временно отключена.", "roulette_disabled")

        state, _ = UserRouletteState.objects.get_or_create(user=locked_user)
        state = UserRouletteState.objects.select_for_update().get(pk=state.pk)
        state.refresh_daily_spins(
            now=now,
            roulette_settings=roulette_settings,
            save=False,
        )
        if state.available_spins <= 0:
            raise _error("Нет доступных попыток.", "no_spins")

        reward_state, _ = UserRouletteRewardState.objects.get_or_create(user=locked_user)
        reward_state = UserRouletteRewardState.objects.select_for_update().get(pk=reward_state.pk)

        prizes = _available_prizes(
            user=locked_user,
            reward_state=reward_state,
            roulette_settings=roulette_settings,
            now=now,
        )
        if not prizes:
            raise _error("Сейчас нет доступных призов для этой рулетки.", "no_available_prizes")

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

        _issue_reward(
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
