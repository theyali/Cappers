from .services import ensure_capper_balance, format_money


def capper_balance(request) -> dict:
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated or not getattr(user, "is_analyst", False):
        return {"nav_capper_balance": None, "nav_capper_balance_display": ""}

    balance = ensure_capper_balance(user).balance
    return {
        "nav_capper_balance": balance,
        "nav_capper_balance_display": format_money(balance),
    }
