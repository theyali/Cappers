from django.db import transaction

from .state import UserRouletteState


@transaction.atomic
def get_user_roulette_state(user, *, now=None) -> UserRouletteState:
    """Refresh under the same user/state locks as a spin or a bonus grant."""
    user.__class__.objects.select_for_update().get(pk=user.pk)
    state = UserRouletteState.for_user(user, refresh=False)
    state = UserRouletteState.objects.select_for_update().get(pk=state.pk)
    state.refresh_daily_spins(now=now)
    return state


@transaction.atomic
def grant_user_roulette_spins(user, amount: int, *, now=None) -> UserRouletteState:
    """Safely grant extra spins from promos, referrals, tournaments or prizes."""
    user.__class__.objects.select_for_update().get(pk=user.pk)

    state, _ = UserRouletteState.objects.get_or_create(user=user)
    state = UserRouletteState.objects.select_for_update().get(pk=state.pk)
    state.refresh_daily_spins(now=now)
    state.grant_spins(amount, save=True)
    return state
