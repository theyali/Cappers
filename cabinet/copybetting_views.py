from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, JsonResponse
from django.template.loader import render_to_string
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, render
from django.core.paginator import Paginator
from django.db.models import Q
from wallets.models import CopyBettingSubscription
from .models import User
from wallets.models import CopyBettingAudiencePreference, CopyBettingLimits
from wallets.forms import CopyBettingLimitsForm
from wallets.services import block_copybetting_user, unblock_copybetting_user

from .services.copybetting import build_audience_csv, build_copybetting_context, build_reader_copybetting_context


@login_required
@require_GET
@never_cache
def audience(request):
    if not request.user.is_analyst:
        raise PermissionDenied
    if request.GET.get("export") == "csv":
        response = HttpResponse(build_audience_csv(request.user, request.GET), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="copybetting-audience.csv"'
        return response
    context = build_copybetting_context(request.user, request.GET)
    return JsonResponse({
        "html": render_to_string("cabinet/includes/_copybetting_content.html", context, request=request),
        "summary_html": render_to_string("cabinet/includes/_copybetting_author_summary.html", context, request=request),
    })


@login_required
@require_GET
@never_cache
def reader(request):
    if request.user.is_analyst:
        raise PermissionDenied
    context = build_reader_copybetting_context(request.user, request.GET)
    return JsonResponse({"html": render_to_string("cabinet/includes/_copybetting_reader_content.html", context, request=request)})


@login_required
@require_POST
@never_cache
def audience_action(request, user_id, action):
    if not request.user.is_analyst:
        raise PermissionDenied
    user = get_object_or_404(User, pk=user_id, role=User.Role.READER)
    if not request.user.copybetting_followers.filter(user=user).exists():
        raise PermissionDenied
    if action == "block":
        block_copybetting_user(analyst=request.user, user=user, reason=request.POST.get("reason", ""))
    elif action == "unblock":
        unblock_copybetting_user(analyst=request.user, user=user)
    else:
        CopyBettingAudiencePreference.objects.update_or_create(analyst=request.user, user=user, defaults={"hidden": action == "hide"})
    return JsonResponse({"ok": True})


@login_required
@require_POST
@never_cache
def limits(request):
    if request.user.is_analyst:
        raise PermissionDenied
    form = CopyBettingLimitsForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"error": " ".join(message for messages in form.errors.values() for message in messages)}, status=400)
    with transaction.atomic():
        User.objects.select_for_update(no_key=True).get(pk=request.user.pk)
        CopyBettingLimits.objects.update_or_create(user=request.user, defaults=form.cleaned_data)
    return JsonResponse({"message": "Общие лимиты сохранены."})


@login_required
@require_GET
@never_cache
def history(request, subscription_id):
    subscription = get_object_or_404(CopyBettingSubscription.objects.filter(Q(user=request.user) | Q(analyst=request.user)).select_related("user", "analyst"), pk=subscription_id)
    page = Paginator(subscription.transitions.select_related("actor").order_by("-created_at", "-id"), 30).get_page(request.GET.get("page", 1))
    return render(request, "cabinet/copybetting_history.html", {"strategy": subscription, "history_page": page})
