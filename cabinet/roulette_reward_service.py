from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import connection

from wallets.services import top_up_virtual_balance

from .roulette_models import RoulettePrize


def issue_roulette_reward(*, spin, prize, user, state, reward_state, now) -> None:
    """Apply the selected roulette reward inside the caller's transaction."""
    if not connection.in_atomic_block:
        raise RuntimeError("Выдача награды рулетки должна выполняться внутри transaction.atomic().")

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
            raise ValidationError("У выпавшего приза не настроен промокод.", code="invalid_promo_reward")
        # Ownership of the promo code is persisted in the user's immutable RouletteSpin snapshot.
        return

    if reward_type == RoulettePrize.RewardType.RATING_BOOST:
        reward_state.grant_rating_boost(reward_value, save=False)
        return

    if reward_type == RoulettePrize.RewardType.EXTRA_SPIN:
        state.grant_spins(int(reward_value), save=False)
        return

    raise ValidationError("Неизвестный тип награды рулетки.", code="unsupported_reward_type")
