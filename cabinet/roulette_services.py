from django.db import transaction

from .roulette_state import UserRouletteState


def get_user_roulette_state(user, *, now=None) -> UserRouletteState:
    """Return a user's current state with the daily allowance refreshed lazily."""
    return UserRouletteState.for_user(user, now=now, refresh=True)


@transaction.atomic
def grant_user_roulette_spins(user, amount: int, *, now=None) -> UserRouletteState:
    """Safely grant extra spins from promos, referrals, tournaments or prizes."""
    # Lock the parent user row as well so two first-time grants cannot race while
    # creating the user's one-to-one roulette state.
    user.__class__.objects.select_for_update().get(pk=user.pk)

    state, _ = UserRouletteState.objects.get_or_create(user=user)
    state = UserRouletteState.objects.select_for_update().get(pk=state.pk)
    state.refresh_daily_spins(now=now, save=False)
    state.grant_spins(amount, save=True)
    return state
