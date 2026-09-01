from .services import ensure_virtual_balance, format_money


def capper_balance(request) -> dict:
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {
            "nav_capper_balance": None,
            "nav_capper_balance_display": "",
            "nav_virtual_balance": None,
            "nav_virtual_balance_display": "",
        }

    balance = ensure_virtual_balance(user).balance
    return {
        "nav_capper_balance": balance,
        "nav_capper_balance_display": format_money(balance),
        "nav_virtual_balance": balance,
        "nav_virtual_balance_display": format_money(balance),
    }
