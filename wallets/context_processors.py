from .services import ensure_coin_wallet, format_coins


def coin_wallet(request) -> dict:
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {
            "nav_coin_balance": None,
            "nav_coin_balance_display": "",
        }

    balance = ensure_coin_wallet(user).balance
    return {
        "nav_coin_balance": balance,
        "nav_coin_balance_display": format_coins(balance),
    }
