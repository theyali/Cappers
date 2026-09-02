from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST, require_http_methods

from cabinet.models import User

from .forms import CopyBettingForm
from .models import CopyBettingSubscription
from .services import (
    InsufficientBalance,
    activate_copybetting,
    ensure_real_balance,
    ensure_virtual_balance,
    format_money,
    pause_copybetting,
    request_real_withdrawal,
    resume_copybetting,
    stop_copybetting,
    top_up_virtual_balance,
    transfer_real_to_virtual,
)


def _ensure_copybetting_reader(user) -> None:
    if user.role == User.Role.ANALYST:
        raise PermissionDenied("Капперы не могут использовать копибеттинг.")


@login_required
@require_http_methods(["GET", "POST"])
def top_up_balance(request):
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

    balance = ensure_virtual_balance(request.user).balance
    real_balance = None
    if request.user.role == User.Role.ANALYST:
        real_balance = ensure_real_balance(request.user)
    return render(
        request,
        "wallets/top_up.html",
        {
            "balance": balance,
            "balance_display": format_money(balance),
            "real_balance": real_balance,
            "real_balance_display": format_money(real_balance.balance) if real_balance else "",
            "pending_withdrawal_display": format_money(real_balance.pending_withdrawal) if real_balance else "",
            "top_up_amount": amount,
            "top_up_amount_display": format_money(amount),
        },
    )


@login_required
@require_POST
def real_balance_action(request):
    if request.user.role != User.Role.ANALYST:
        raise PermissionDenied("Реальный баланс доступен только капперам.")

    action = request.POST.get("action")
    amount = request.POST.get("amount")
    try:
        if action == "transfer_to_virtual":
            transfer_real_to_virtual(request.user, amount)
            messages.success(request, "Средства переведены на виртуальный баланс.")
        elif action == "withdraw":
            request_real_withdrawal(request.user, amount)
            messages.success(request, "Заявка на вывод создана.")
        else:
            messages.error(request, "Неизвестное действие с балансом.")
    except (ValidationError, InsufficientBalance) as exc:
        messages.error(request, _error_message(exc))

    return redirect(_safe_next(request, reverse("wallets:top_up")))


@login_required
@require_http_methods(["GET", "POST"])
def copybetting_setup(request, analyst_id: int):
    _ensure_copybetting_reader(request.user)

    analyst = get_object_or_404(
        User.objects.select_related("analyst_profile"),
        pk=analyst_id,
        role=User.Role.ANALYST,
        is_active=True,
    )
    if analyst.pk == request.user.pk:
        raise PermissionDenied("Нельзя копировать самого себя.")

    subscription = CopyBettingSubscription.objects.filter(
        user=request.user,
        analyst=analyst,
    ).first()
    form = CopyBettingForm(request.POST or None, instance=subscription)
    if request.method == "POST" and form.is_valid():
        try:
            subscription = activate_copybetting(
                user=request.user,
                analyst=analyst,
                bank_amount=form.cleaned_data["bank_amount"],
                stake_percent=form.cleaned_data["stake_percent"],
                stop_loss_amount=form.cleaned_data["stop_loss_amount"],
                max_single_stake=form.cleaned_data["max_single_stake"],
                min_total_coefficient=form.cleaned_data["min_total_coefficient"],
                copy_regular_coupons=form.cleaned_data["copy_regular_coupons"],
                copy_tournament_coupons=form.cleaned_data["copy_tournament_coupons"],
                allowed_sports=form.cleaned_data["allowed_sports"],
            )
        except ValidationError as exc:
            form.add_error(None, _error_message(exc))
        else:
            messages.success(request, "Копибеттинг включен.")
            return redirect(f"{reverse('cabinet:profile')}?tab=copybetting")

    expert_name = analyst.username
    profile = getattr(analyst, "analyst_profile", None)
    if profile:
        expert_name = profile.display_name or analyst.get_full_name() or analyst.username

    return render(
        request,
        "wallets/copybetting_setup.html",
        {
            "form": form,
            "analyst": analyst,
            "expert_name": expert_name,
            "subscription": subscription,
            "virtual_balance": ensure_virtual_balance(request.user),
        },
    )


@login_required
@require_POST
def copybetting_stop(request, subscription_id: int):
    _ensure_copybetting_reader(request.user)
    subscription = get_object_or_404(
        CopyBettingSubscription,
        pk=subscription_id,
        user=request.user,
    )
    stop_copybetting(subscription)
    messages.success(request, "Копибеттинг остановлен.")
    return redirect(f"{reverse('cabinet:profile')}?tab=copybetting")


@login_required
@require_POST
def copybetting_pause(request, subscription_id: int):
    _ensure_copybetting_reader(request.user)
    subscription = get_object_or_404(
        CopyBettingSubscription,
        pk=subscription_id,
        user=request.user,
    )
    pause_copybetting(subscription)
    messages.success(request, "Копибеттинг поставлен на паузу.")
    return redirect(f"{reverse('cabinet:profile')}?tab=copybetting")


@login_required
@require_POST
def copybetting_resume(request, subscription_id: int):
    _ensure_copybetting_reader(request.user)
    subscription = get_object_or_404(
        CopyBettingSubscription,
        pk=subscription_id,
        user=request.user,
    )
    resume_copybetting(subscription)
    messages.success(request, "Копибеттинг возобновлен.")
    return redirect(f"{reverse('cabinet:profile')}?tab=copybetting")


def _safe_next(request, fallback: str) -> str:
    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or ""
    if not url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return fallback
    return next_url


def _error_message(exc) -> str:
    if isinstance(exc, ValidationError):
        return exc.messages[0] if exc.messages else str(exc)
    return str(exc)
