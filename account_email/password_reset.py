from django.contrib.auth.forms import SetPasswordForm
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_GET
from django.views.generic import FormView, TemplateView

from .forms import AccountPasswordResetForm
from .services import (
    PasswordResetError,
    complete_password_reset,
    consume_password_reset_link,
    get_opened_password_reset,
)


PASSWORD_RESET_SESSION_KEY = "account_email_password_reset_request_id"
PASSWORD_RESET_INVISIBLE_CHARS = "\u200b\u200c\u200d\u2060\ufeff"


class AccountPasswordResetView(FormView):
    template_name = "cabinet/auth/password_reset_form.html"
    form_class = AccountPasswordResetForm
    success_url = reverse_lazy("cabinet:password_reset_done")

    def form_valid(self, form):
        form.save(request=self.request)
        return super().form_valid(form)


class AccountPasswordResetDoneView(TemplateView):
    template_name = "cabinet/auth/password_reset_done.html"


@require_GET
def consume_password_reset(request, uidb64: str, token: str, trailing: str = ""):
    uidb64 = _remove_invisible_chars(uidb64)
    token = _remove_invisible_chars(token)

    try:
        flow = consume_password_reset_link(uidb64, token)
    except PasswordResetError:
        return render(
            request,
            "cabinet/auth/password_reset_confirm.html",
            {"validlink": False},
        )

    request.session[PASSWORD_RESET_SESSION_KEY] = flow.pk
    request.session.modified = True
    return redirect("cabinet:password_reset_set")


def set_new_password(request):
    flow_id = request.session.get(PASSWORD_RESET_SESSION_KEY)
    flow = get_opened_password_reset(flow_id) if flow_id else None
    if flow is None:
        _clear_reset_session(request)
        return render(
            request,
            "cabinet/auth/password_reset_confirm.html",
            {"validlink": False},
        )

    form = SetPasswordForm(flow.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            complete_password_reset(flow.pk, form.cleaned_data["new_password1"])
        except PasswordResetError:
            _clear_reset_session(request)
            return render(
                request,
                "cabinet/auth/password_reset_confirm.html",
                {"validlink": False},
            )

        _clear_reset_session(request)
        return redirect("cabinet:password_reset_complete")

    return render(
        request,
        "cabinet/auth/password_reset_confirm.html",
        {"validlink": True, "form": form},
    )


class AccountPasswordResetCompleteView(TemplateView):
    template_name = "cabinet/auth/password_reset_complete.html"


def _remove_invisible_chars(value: str) -> str:
    return "".join(char for char in value if char not in PASSWORD_RESET_INVISIBLE_CHARS)


def _clear_reset_session(request) -> None:
    request.session.pop(PASSWORD_RESET_SESSION_KEY, None)
    request.session.modified = True
