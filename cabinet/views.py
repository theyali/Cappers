from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .forms import AnalystProfileForm, RegistrationForm, UserProfileForm
from .models import AnalystProfile, User
from .permissions import analyst_required, reader_required


@require_http_methods(["GET", "POST"])
def register(request):
    if request.user.is_authenticated:
        return redirect("cabinet:dashboard")

    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = form.save()
        login(request, user)
        messages.success(request, "Регистрация завершена.")
        return redirect("cabinet:dashboard")

    return render(request, "cabinet/auth/register.html", {"form": form})


@login_required
def dashboard(request):
    if request.user.role == User.Role.ANALYST:
        return redirect("cabinet:analyst_dashboard")
    return redirect("cabinet:reader_dashboard")


@reader_required
def reader_dashboard(request):
    return render(request, "cabinet/reader_dashboard.html")


@analyst_required
def analyst_dashboard(request):
    analyst_profile, _ = AnalystProfile.objects.get_or_create(user=request.user)
    return render(
        request,
        "cabinet/analyst_dashboard.html",
        {"analyst_profile": analyst_profile},
    )


@login_required
def profile(request):
    analyst_profile = None
    if request.user.role == User.Role.ANALYST:
        analyst_profile, _ = AnalystProfile.objects.get_or_create(user=request.user)

    return render(
        request,
        "cabinet/profile.html",
        {"analyst_profile": analyst_profile},
    )


@login_required
@require_http_methods(["GET", "POST"])
def edit_profile(request):
    analyst_profile = None
    if request.user.role == User.Role.ANALYST:
        analyst_profile, _ = AnalystProfile.objects.get_or_create(user=request.user)

    user_form = UserProfileForm(request.POST or None, instance=request.user)
    analyst_form = None

    if analyst_profile is not None:
        analyst_form = AnalystProfileForm(
            request.POST or None,
            request.FILES or None,
            instance=analyst_profile,
        )

    if request.method == "POST":
        user_is_valid = user_form.is_valid()
        analyst_is_valid = analyst_form.is_valid() if analyst_form is not None else True

        if user_is_valid and analyst_is_valid:
            with transaction.atomic():
                user_form.save()
                if analyst_form is not None:
                    analyst_form.save()
            messages.success(request, "Профиль обновлён.")
            return redirect("cabinet:profile")

    return render(
        request,
        "cabinet/profile_edit.html",
        {
            "user_form": user_form,
            "analyst_form": analyst_form,
        },
    )
