from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods

from cabinet.models import User

from .services import ensure_capper_balance, format_money, top_up_virtual_balance


@login_required
@require_http_methods(["GET", "POST"])
def top_up_balance(request):
    if request.user.role != User.Role.ANALYST:
        raise PermissionDenied("Баланс доступен только капперам.")

    amount = getattr(settings, "CAPPER_VIRTUAL_TOP_UP_AMOUNT", "10000.00")
    if request.method == "POST":
        try:
            top_up_virtual_balance(request.user, amount)
        except ValidationError as exc:
            messages.error(request, exc.messages[0] if exc.messages else str(exc))
        else:
            messages.success(request, f"Баланс пополнен на {format_money(amount)} ₽.")

        next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or ""
        if not url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        ):
            next_url = "wallets:top_up"
        return redirect(next_url)

    balance = ensure_capper_balance(request.user).balance
    return render(
        request,
        "wallets/top_up.html",
        {
            "balance": balance,
            "balance_display": format_money(balance),
            "top_up_amount": amount,
            "top_up_amount_display": format_money(amount),
        },
    )
