import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Prefetch
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from wallets.services import InsufficientBalance, ensure_real_balance, format_money

from .models import VipPlan, VipPlanComparisonFeature, VipPlanComparisonValue
from .vip import get_active_vip, purchase_vip


def _plural_ru(value: int, one: str, few: str, many: str) -> str:
    value = abs(int(value))
    if value % 10 == 1 and value % 100 != 11:
        return one
    if 2 <= value % 10 <= 4 and not 12 <= value % 100 <= 14:
        return few
    return many


def _vip_time_left(subscription) -> str:
    if subscription is None:
        return ""
    remaining = subscription.ends_at - timezone.now()
    if remaining.total_seconds() <= 0:
        return "истёк"
    days = remaining.days
    if days > 0:
        return f"{days} {_plural_ru(days, 'день', 'дня', 'дней')}"
    hours = max(1, int(remaining.total_seconds() // 3600))
    return f"{hours} {_plural_ru(hours, 'час', 'часа', 'часов')}"


def _wants_json(request) -> bool:
    return (
        (request.content_type or "").startswith("application/json")
        or "application/json" in request.headers.get("Accept", "")
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
    )


def _request_plan_id(request):
    plan_id = request.POST.get("plan_id")
    if plan_id:
        return plan_id

    if request.content_type == "application/json":
        try:
            payload = json.loads(request.body or b"{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return payload.get("plan_id")
    return None


def _error_message(exc) -> str:
    if isinstance(exc, ValidationError):
        return exc.messages[0] if exc.messages else str(exc)
    return str(exc)


def _vip_comparison_rows(plans):
    values_queryset = VipPlanComparisonValue.objects.filter(plan__in=plans).select_related("plan")
    features = (
        VipPlanComparisonFeature.objects.filter(is_active=True)
        .prefetch_related(Prefetch("values", queryset=values_queryset))
        .order_by("order", "id")
    )

    rows = []
    for feature in features:
        values_by_plan = {value.plan_id: value for value in feature.values.all()}
        rows.append(
            {
                "feature": feature,
                "cells": [
                    {
                        "plan": plan,
                        "value": values_by_plan.get(plan.id),
                    }
                    for plan in plans
                ],
            }
        )
    return rows


@login_required
def vip_plans(request):
    if not getattr(request.user, "is_analyst", False):
        raise PermissionDenied("VIP-тарифы доступны только капперам.")

    real_balance = ensure_real_balance(request.user)
    active_vip = get_active_vip(request.user)
    plans = list(VipPlan.objects.filter(is_active=True).order_by("order", "duration_days", "id"))
    balance_amount = real_balance.balance
    for plan in plans:
        plan.can_afford = balance_amount >= plan.price_rub
        plan.balance_after = balance_amount - plan.price_rub
        plan.price_display = format_money(plan.price_rub)
        plan.balance_after_display = format_money(plan.balance_after) if plan.can_afford else ""
    comparison_rows = _vip_comparison_rows(plans)

    return render(
        request,
        "cabinet/vip_plans.html",
        {
            "active_tab": "vip",
            "page_class": "cabinet-vip-page profile",
            "plans": plans,
            "active_vip": active_vip,
            "vip_time_left": _vip_time_left(active_vip),
            "real_balance": real_balance,
            "real_balance_display": format_money(real_balance.balance),
            "comparison_rows": comparison_rows,
            "page": {
                "title": "VIP-тарифы — КапперХаб",
                "heading": "VIP-тарифы",
                "description": "Выберите срок VIP-доступа и оплатите его с реального баланса.",
                "mobile_nav_label": "Разделы профиля",
                "profile_nav_label": "Разделы профиля",
            },
        },
    )


@login_required
@require_POST
def vip_purchase(request):
    plan_id = _request_plan_id(request)
    if not plan_id:
        if not _wants_json(request):
            messages.error(request, "Не выбран VIP-тариф.")
            return redirect(reverse("cabinet:vip_plans"))
        return JsonResponse(
            {"ok": False, "error": "Не выбран VIP-тариф."},
            status=400,
        )

    plan = get_object_or_404(VipPlan, pk=plan_id, is_active=True)
    try:
        subscription, real_balance = purchase_vip(request.user, plan)
    except (ValidationError, InsufficientBalance) as exc:
        if not _wants_json(request):
            messages.error(request, _error_message(exc))
            return redirect(reverse("cabinet:vip_plans"))
        return JsonResponse(
            {"ok": False, "error": _error_message(exc)},
            status=400,
        )

    if not _wants_json(request):
        messages.success(
            request,
            f"VIP «{subscription.plan.title if subscription.plan else 'тариф'}» активен до {subscription.ends_at:%d.%m.%Y}.",
        )
        return redirect(reverse("cabinet:vip_plans"))

    return JsonResponse(
        {
            "ok": True,
            "subscription": {
                "id": subscription.pk,
                "plan_id": subscription.plan_id,
                "starts_at": subscription.starts_at.isoformat(),
                "ends_at": subscription.ends_at.isoformat(),
                "duration_days": subscription.duration_days,
                "source": subscription.source,
            },
            "real_balance": str(real_balance.balance),
            "real_balance_display": f"{format_money(real_balance.balance)} ₽",
        }
    )
