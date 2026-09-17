from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import connection

from cabinet.models import UserVipSubscription
from cabinet.vip import extend_vip
from wallets.models import CoinTransaction
from wallets.services import credit_coins

from .models import RoulettePrize


def issue_roulette_reward(*, spin, prize, user, state, reward_state, now) -> None:
    """Apply the selected roulette reward inside the caller's transaction."""
    if not connection.in_atomic_block:
        raise RuntimeError("Выдача награды рулетки должна выполняться внутри transaction.atomic().")

    reward_type = prize.reward_type
    reward_value = Decimal(str(prize.reward_value or 0))

    if reward_type == RoulettePrize.RewardType.NOTHING:
        return

    if reward_type == RoulettePrize.RewardType.COINS:
        coin_amount = int(reward_value)
        if reward_value != Decimal(coin_amount) or coin_amount <= 0:
            raise ValidationError(
                "Приз рулетки в коинах должен быть положительным целым числом.",
                code="invalid_coin_reward",
            )
        credit_coins(
            user,
            coin_amount,
            CoinTransaction.Kind.ROULETTE_REWARD,
            related_obj=spin,
            note=f"Приз рулетки: {prize.title} · операция {spin.operation_id}",
        )
        return

    if reward_type == RoulettePrize.RewardType.VIP_DAYS:
        days = int(reward_value)
        subscription = extend_vip(
            user,
            days,
            UserVipSubscription.Source.ROULETTE,
            starts_at=now,
        )
        # Compatibility cache for the existing roulette state/API. The source of
        # truth for VIP status is UserVipSubscription.
        reward_state.vip_until = subscription.ends_at
        return

    if reward_type == RoulettePrize.RewardType.FREE_PREDICTIONS:
        reward_state.grant_free_predictions(int(reward_value), save=False)
        return

    if reward_type == RoulettePrize.RewardType.PROMO_CODE:
        if not prize.reward_text.strip():
            raise ValidationError(
                "У выпавшего приза не настроен промокод.",
                code="invalid_promo_reward",
            )
        return

    if reward_type == RoulettePrize.RewardType.RATING_BOOST:
        reward_state.grant_rating_boost(reward_value, save=False)
        return

    if reward_type == RoulettePrize.RewardType.EXTRA_SPIN:
        state.grant_spins(int(reward_value), save=False)
        return

    raise ValidationError(
        "Неизвестный тип награды рулетки.",
        code="unsupported_reward_type",
    )
