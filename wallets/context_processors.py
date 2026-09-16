from django.db.utils import OperationalError, ProgrammingError

from .models import CoinWallet
from .services import ensure_coin_wallet, format_coins


def coin_wallet(request) -> dict:
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {
            "nav_coin_balance": None,
            "nav_coin_balance_display": "",
        }

    try:
        balance = (
            CoinWallet.objects.filter(user_id=user.pk)
            .values_list("balance", flat=True)
            .first()
        )
        if balance is None:
            # Preserve the existing initial-grant behavior only for users who
            # genuinely do not have a wallet yet. Normal page renders stay read-only.
            balance = ensure_coin_wallet(user).balance
    except (OperationalError, ProgrammingError):
        balance = 0

    return {
        "nav_coin_balance": balance,
        "nav_coin_balance_display": format_coins(balance),
    }
