from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST, require_http_methods

from .forms import EmailAddressForm, EmailCodeForm
from .models import EmailChangeRequest
from .services import (
    EmailChangeError,
    complete_email_change,
    confirm_current_email_token,
    send_change_new_email_code,
    start_add_email,
    start_change_confirmation,
)


def _profile_settings_url() -> str:
    return f"{reverse('cabinet:profile')}?tab=settings"


@login_required
@require_POST
def add_email(request):
    if request.user.email:
        messages.error(request, "Почта уже указана. Используйте смену почты.")
        return redirect(_profile_settings_url())

    form = EmailAddressForm(request.POST, user=request.user)
    if not form.is_valid():
        messages.error(request, _first_form_error(form))
        return redirect(_profile_settings_url())

    try:
        flow = start_add_email(request.user, form.cleaned_data["new_email"])
    except EmailChangeError as exc:
        messages.error(request, str(exc))
        return redirect(_profile_settings_url())

    messages.success(request, "Код подтверждения отправлен на новую почту.")
    return redirect("account_email:verify", request_id=flow.pk)


@login_required
@require_POST
def request_email_change(request):
    try:
        start_change_confirmation(request.user, request)
    except EmailChangeError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            "Ссылка для смены почты отправлена на вашу текущую почту.",
        )
    return redirect(_profile_settings_url())


@login_required
@require_http_methods(["GET", "POST"])
def confirm_change(request, token: str):
    try:
        flow = confirm_current_email_token(request.user, token)
    except EmailChangeError as exc:
        messages.error(request, str(exc))
        return redirect(_profile_settings_url())

    form = EmailAddressForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            send_change_new_email_code(flow, request.user, form.cleaned_data["new_email"])
        except EmailChangeError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Код подтверждения отправлен на новую почту.")
            return redirect("account_email:verify", request_id=flow.pk)
    elif request.method == "POST":
        messages.error(request, _first_form_error(form))

    return render(
        request,
        "account_email/enter_new_email.html",
        {
            "form": form,
            "flow": flow,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def verify_new_email(request, request_id: int):
    flow = get_object_or_404(
        EmailChangeRequest,
        pk=request_id,
        user=request.user,
        completed_at__isnull=True,
    )
    form = EmailCodeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            complete_email_change(request.user, flow.pk, form.cleaned_data["code"])
        except EmailChangeError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Почта аккаунта обновлена.")
            return redirect(_profile_settings_url())
    elif request.method == "POST":
        messages.error(request, _first_form_error(form))

    return render(
        request,
        "account_email/verify_new_email.html",
        {
            "form": form,
            "flow": flow,
        },
    )


def _first_form_error(form) -> str:
    for errors in form.errors.values():
        if errors:
            return str(errors[0])
    return "Проверьте данные формы."
