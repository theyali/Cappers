import secrets

from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.utils import timezone

from front.models import PredictionFavorite, PredictionLike

from ..roulette_history import RouletteSpin
from ..roulette_models import RoulettePrize, RouletteSettings
from ..roulette_rewards import UserRouletteRewardState
from ..roulette_state import roulette_daily_window
from .errors import roulette_error


MAX_ACTIVE_ROULETTE_SECTORS = 10


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


def available_prizes(*, user, reward_state, roulette_settings, now, lock=False):
    window_start, next_reset = roulette_daily_window(roulette_settings, now)
    activity_count = _activity_count(user)

    queryset = (
        RoulettePrize.objects.filter(is_active=True)
        .filter(Q(active_from__isnull=True) | Q(active_from__lte=now))
        .filter(Q(active_until__isnull=True) | Q(active_until__gt=now))
        .prefetch_related("conditions")
        .order_by("sector_order", "id")
    )
    if lock:
        queryset = queryset.select_for_update()

    prizes = list(queryset)
    eligible = [
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
    return eligible[:MAX_ACTIVE_ROULETTE_SECTORS]


def get_available_roulette_prizes(*, user, now=None):
    """Return sectors the current user can actually win, without exposing weights."""
    if not getattr(user, "is_authenticated", False):
        raise PermissionDenied("Войдите, чтобы посмотреть рулетку.")

    now = now or timezone.now()
    roulette_settings = RouletteSettings.load()
    if not roulette_settings.is_enabled:
        return []

    reward_state, _ = UserRouletteRewardState.objects.get_or_create(user=user)
    return available_prizes(
        user=user,
        reward_state=reward_state,
        roulette_settings=roulette_settings,
        now=now,
        lock=False,
    )


def choose_weighted_prize(prizes):
    total_weight = sum(int(prize.weight) for prize in prizes)
    if total_weight <= 0:
        raise roulette_error(
            "Для рулетки не настроены корректные веса призов.",
            "invalid_prize_weights",
        )

    ticket = secrets.randbelow(total_weight)
    cursor = 0
    for prize in prizes:
        cursor += int(prize.weight)
        if ticket < cursor:
            return prize
    return prizes[-1]
