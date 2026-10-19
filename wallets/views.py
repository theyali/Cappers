from urllib.parse import urlsplit

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST, require_http_methods
from django.views.decorators.cache import never_cache
from django.template.loader import render_to_string

from back.models import WebsiteSettings
from cabinet.models import User
from cabinet.telegram_auth import in_telegram_app
from payments.utils import build_payment_options

from .copybetting_ui import build_capper_search_context, build_setup_context
from .forms import CopyBettingForm
from .context_processors import BALANCE_HIDDEN_SESSION_KEY
from .models import CoinPackage, CoinWallet, CopyBettingSubscription
from .services import (
    InsufficientBalance,
    activate_copybetting,
    ensure_coin_wallet,
    ensure_real_balance,
    format_coins,
    format_money,
    pause_copybetting,
    request_real_withdrawal,
    resume_copybetting,
    stop_copybetting,
)


def _ensure_copybetting_reader(user) -> None:
    if user.role == User.Role.ANALYST:
        raise PermissionDenied("Капперы не могут использовать копибеттинг.")


@login_required
@require_POST
def balance_visibility(request):
    raw_hidden = str(request.POST.get("hidden", "")).lower()
    hidden = raw_hidden in {"1", "true", "yes", "on"}
    request.session[BALANCE_HIDDEN_SESSION_KEY] = hidden
    request.session.modified = True

    balance = ensure_coin_wallet(request.user).balance
    return JsonResponse(
        {
            "ok": True,
            "hidden": hidden,
            "balance_display": format_coins(balance),
            "masked_display": "***",
        }
    )


@login_required
@require_http_methods(["GET", "POST"])
def top_up_balance(request):
    wallet = ensure_coin_wallet(request.user)
    packages = list(CoinPackage.objects.filter(is_active=True).order_by("order", "id"))
    for package in packages:
        package.payment_options = build_payment_options(
            package.price_rub, request.user, in_telegram_app=in_telegram_app(request)
        )
    default_package = packages[2] if len(packages) >= 3 else (packages[0] if packages else None)

    if request.method == "POST":
        package_id = request.POST.get("package_id")
        if package_id:
            package = get_object_or_404(CoinPackage, pk=package_id, is_active=True)
            messages.info(
                request,
                f"Покупка пакета «{package.title}» за {format_money(package.price_rub)} ₽ будет доступна после подключения платежного сценария.",
            )
        else:
            messages.info(
                request,
                "Покупка пакетов коинов будет доступна после подключения платежного сценария.",
            )
        return redirect(_safe_next(request, reverse("wallets:top_up")))

    real_balance = None
    if request.user.role == User.Role.ANALYST:
        real_balance = ensure_real_balance(request.user)

    return render(
        request,
        "wallets/top_up.html",
        {
            "coin_wallet": wallet,
            "coin_balance": wallet.balance,
            "coin_balance_display": format_coins(wallet.balance),
            "coin_packages": packages,
            "default_coin_package": default_package,
            "real_balance": real_balance,
            "real_balance_display": format_money(real_balance.balance) if real_balance else "",
            "pending_withdrawal_display": format_money(real_balance.pending_withdrawal) if real_balance else "",
            "held_display": format_money(real_balance.held) if real_balance and real_balance.held else "",
            "min_withdrawal_display": format_money(WebsiteSettings.load().min_withdrawal_amount),
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
        if action == "withdraw":
            request_real_withdrawal(
                request.user,
                amount,
                payout_details=request.POST.get("payout_details", ""),
            )
            messages.success(request, "Заявка на вывод создана.")
        else:
            messages.error(request, "Неизвестное действие с реальным балансом.")
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

    wallet = ensure_coin_wallet(request.user)
    return render(
        request,
        "wallets/copybetting_setup.html",
        {
            "form": form,
            "analyst": analyst,
            "expert_name": expert_name,
            "subscription": subscription,
            "coin_wallet": wallet,
            **build_setup_context(request.user, analyst, form, balance=wallet.balance),
        },
    )


@login_required
@require_POST
@never_cache
def copybetting_status(request, subscription_id: int, action: str):
    _ensure_copybetting_reader(request.user)
    subscription = get_object_or_404(
        CopyBettingSubscription.objects.select_related("analyst", "analyst__analyst_profile"),
        pk=subscription_id, user=request.user,
    )
    ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"
    try:
        subscription = {"pause": pause_copybetting, "stop": stop_copybetting, "resume": resume_copybetting}[action](subscription)
    except ValidationError as exc:
        if ajax:
            return JsonResponse({"error": _error_message(exc)}, status=400)
        messages.error(request, _error_message(exc))
    else:
        notice = {
            "pause": "Копибеттинг поставлен на паузу.",
            "stop": "Копибеттинг остановлен.",
            "resume": "Копибеттинг возобновлен.",
        }[action]
        if subscription.pending_status:
            notice = f"{subscription.get_pending_status_display()} — после расчёта уже начавшихся купонов."
        if ajax:
            from cabinet.services.copybetting import build_public_copybetting_context, build_reader_copybetting_context
            payload = {"message": notice, "status": subscription.status, "pending_status": subscription.pending_status}
            if request.POST.get("surface") == "reader":
                params = QueryDict(urlsplit(request.POST.get("next", "")).query)
                context = build_reader_copybetting_context(request.user, params)
                payload["reader_html"] = render_to_string("cabinet/includes/_copybetting_reader_content.html", context, request=request)
                payload["summary_html"] = render_to_string("cabinet/includes/_copybetting_reader_summary.html", context, request=request)
            else:
                context = build_public_copybetting_context(request.user, subscription.analyst)
                context["expert_name"] = subscription.analyst.analyst_profile.display_name or subscription.analyst.username
                for variant in ("desktop", "mobile"):
                    payload[f"{variant}_html"] = render_to_string("cabinet/includes/_expert_copybetting_bar.html", {**context, "copy_variant": variant}, request=request)
                    payload[f"{variant}_button_html"] = render_to_string("cabinet/includes/_expert_copybetting_button.html", {**context, "copy_mobile": variant == "mobile"}, request=request)
            return JsonResponse(payload)
        messages.success(request, notice)
    return redirect(_safe_next(request, f"{reverse('cabinet:profile')}?tab=copybetting"))


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


@login_required
@require_POST
@never_cache
def copybetting_search(request):
    _ensure_copybetting_reader(request.user)
    context = build_capper_search_context(request.user, request.POST)
    return JsonResponse({"html": render_to_string("wallets/includes/_copybetting_search_results.html", context, request=request)})


@login_required
@require_POST
@never_cache
def copybetting_preview(request, analyst_id):
    _ensure_copybetting_reader(request.user)
    analyst = get_object_or_404(User, pk=analyst_id, role=User.Role.ANALYST, is_active=True)
    form = CopyBettingForm(request.POST)
    balance = CoinWallet.objects.filter(user=request.user).values_list("balance", flat=True).first() or 0
    context = build_setup_context(request.user, analyst, form, balance=balance)
    return JsonResponse({"html": render_to_string("wallets/includes/_copybetting_setup_preview.html", context, request=request),
                         "calculation": render_to_string("wallets/includes/_copybetting_calculation.html", context, request=request),
                         "valid": form.is_valid(), "errors": context["setup_validation_errors"]})
