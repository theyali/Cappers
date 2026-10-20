from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods

from cappers.ratelimit import rate_limited
from game.models import PredictionCoupon
from wallets.services import InsufficientBalance

from .paid_predictions import user_can_view_paid_coupon
from .paid_prediction_purchases import (
    build_single_checkout_context, buy_coupon_with_balance, coupon_purchase_history,
)
from .telegram_auth import in_telegram_app


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def checkout(request, coupon_id):
    coupon = get_object_or_404(PredictionCoupon.objects.select_related("author__analyst_profile"),
        pk=coupon_id, published_status=PredictionCoupon.PublishedStatus.PUBLISHED, audience=PredictionCoupon.Audience.PAID)
    wants_json = request.headers.get("x-requested-with") == "XMLHttpRequest"
    detail_url = reverse("front:prediction_detail", args=[coupon.pk])
    accessible = user_can_view_paid_coupon(request.user, coupon)
    if accessible:
        if wants_json:
            if request.method == "POST":
                html = render_to_string("cabinet/includes/_single_coupon_purchase_success.html", {"coupon": coupon}, request=request)
                return JsonResponse({"ok": True, "html": html, "return_url": detail_url})
            return render(request, "cabinet/includes/_single_coupon_purchase_success.html", {"coupon": coupon})
        return redirect(detail_url)
    if request.method == "GET" and not wants_json:
        next_url = request.GET.get("next") or request.META.get("HTTP_REFERER") or detail_url
        if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()) or urlsplit(next_url).path == request.path:
            next_url = detail_url
        target = urlsplit(next_url)
        query = [(key, value) for key, value in parse_qsl(target.query) if key != "buy_coupon"]
        query.append(("buy_coupon", str(coupon.pk)))
        return redirect(urlunsplit(target._replace(query=urlencode(query))))
    error = ""
    if request.method == "POST":
        if not request.user.is_analyst:
            error = "Выберите способ прямой оплаты."
            if wants_json:
                return JsonResponse({"ok": False, "message": error}, status=403)
        elif rate_limited(f"single-coupon-buy:{request.user.pk}", limit=20, window=60):
            error = "Слишком много запросов. Попробуйте через минуту."
        else:
            try:
                buy_coupon_with_balance(request.user, coupon)
            except (ValidationError, InsufficientBalance) as exc:
                error = exc.messages[0] if isinstance(exc, ValidationError) else str(exc)
            else:
                if wants_json:
                    html = render_to_string("cabinet/includes/_single_coupon_purchase_success.html", {"coupon": coupon}, request=request)
                    return JsonResponse({"ok": True, "html": html, "return_url": detail_url})
                return redirect(detail_url)
        if wants_json:
            return JsonResponse({"ok": False, "message": error}, status=400)
        messages.error(request, error)
        return redirect(request.path)
    return render(request, "cabinet/includes/_single_coupon_checkout.html",
        {**build_single_checkout_context(request.user, coupon, in_telegram_app=in_telegram_app(request)), "purchase_error": error})


@login_required
@never_cache
@require_GET
def purchases(request, *, sales=False):
    if sales and not request.user.is_analyst:
        raise PermissionDenied
    refunded = request.GET.get("status") == "refunded"
    rows, totals = coupon_purchase_history(request.user, sales=sales, refunded=refunded)
    return render(request, "cabinet/coupon_purchases.html", {
        "seo_meta": {"robots": "noindex,nofollow"},
        "page_obj": Paginator(rows, 20).get_page(request.GET.get("page")),
        "sales": sales, "refunded": refunded, "totals": totals,
        "page_title": "Продажи купонов" if sales else "Купленные купоны",
        "active_tab": "coupon_sales" if sales else "purchases",
    })
