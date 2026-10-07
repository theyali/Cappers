import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponseBadRequest, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from cabinet.services.registration_guard import client_ip
from cappers.ratelimit import rate_limited
from payments.models import Payment
from payments.services.checkout import coin_package_order, paid_subscription_order, start_checkout, vip_plan_order
from payments.services.processing import apply_provider_event
from payments.services.providers.base import InvalidSignature, PaymentProviderError
from payments.services.providers.factory import PaymentProviderFactory
from payments.utils import build_payment_return_context, build_payment_status

logger = logging.getLogger("payments")

# Orders a user may start per 10 minutes; reopening the same order counts too.
CHECKOUT_ATTEMPTS_LIMIT = 10


@login_required
@require_POST
def checkout(request, purpose: str):
    data = request.POST
    analyst_id = data.get("analyst_id", "")
    back_urls = {
        Payment.Purpose.COIN_PACKAGE: reverse("wallets:top_up"),
        Payment.Purpose.VIP_PLAN: reverse("cabinet:vip_plans"),
        Payment.Purpose.PAID_SUBSCRIPTION: (
            reverse("cabinet:paid_predictions_subscribe", args=[analyst_id])
            if analyst_id.isdigit()
            else reverse("front:index")
        ),
    }
    if purpose not in back_urls:
        raise Http404
    back_url = back_urls[purpose]
    if rate_limited(f"payments:checkout:{request.user.pk}", limit=CHECKOUT_ATTEMPTS_LIMIT, window=10 * 60):
        messages.error(request, "Слишком много попыток оплаты. Попробуйте через несколько минут.")
        return redirect(back_url)

    try:
        if purpose == Payment.Purpose.COIN_PACKAGE:
            order = coin_package_order(data.get("package_id"))
        elif purpose == Payment.Purpose.PAID_SUBSCRIPTION:
            order = paid_subscription_order(request.user, analyst_id, data.get("plan_id") or None)
        else:
            order = vip_plan_order(request.user, data.get("plan_id"), switch=data.get("purchase_mode") == "switch")
        payment = start_checkout(request.user, order, data.get("provider", ""), site_url=request.build_absolute_uri("/"))
    except ValidationError as exc:
        messages.error(request, exc.messages[0] if exc.messages else str(exc))
        return redirect(back_url)
    return redirect(payment.checkout_url)


@login_required
@require_GET
def payment_return(request, public_id):
    payment = get_object_or_404(Payment, public_id=public_id, user=request.user)
    return render(request, "payments/return.html", build_payment_return_context(payment))


@login_required
@require_GET
def payment_status(request, public_id):
    payment = get_object_or_404(Payment, public_id=public_id, user=request.user)
    return JsonResponse(build_payment_status(payment))


@csrf_exempt
@require_POST
def provider_webhook(request, provider_code: str, event_type: str):
    try:
        provider = PaymentProviderFactory.create(provider_code)
    except PaymentProviderError:
        raise Http404
    try:
        provider.verify_signature(request)
        event = provider.parse_webhook(request, event_type=event_type)
    except InvalidSignature:
        logger.warning("Rejected %s %s notification with a bad signature from %s", provider_code, event_type, client_ip(request))
        return HttpResponseForbidden()
    except PaymentProviderError as error:
        logger.warning("Rejected %s %s notification: %s", provider_code, event_type, error)
        return HttpResponseBadRequest()
    return provider.webhook_response(rejection=apply_provider_event(provider_code, event))
