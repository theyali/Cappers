from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST, require_http_methods

from .forms import (
    AnalystAvatarForm,
    AnalystProfileForm,
    RegistrationForm,
    UserProfileForm,
)
from .models import AnalystFollow, AnalystProfile, User


@require_http_methods(["GET", "POST"])
def register(request):
    if request.user.is_authenticated:
        return redirect("cabinet:profile")

    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = form.save()
        login(request, user)
        messages.success(request, "Регистрация завершена.")
        return redirect("cabinet:profile")

    return render(request, "cabinet/auth/register.html", {"form": form})


@login_required
def dashboard(request):
    return redirect("cabinet:profile")


@login_required
def legacy_reader_dashboard(request):
    return redirect("cabinet:profile")


@login_required
def legacy_analyst_dashboard(request):
    return redirect("cabinet:profile")


def _get_analyst_profile(user):
    if user.role != User.Role.ANALYST:
        return None
    profile, _ = AnalystProfile.objects.get_or_create(user=user)
    return profile


def _profile_completion(user, analyst_profile) -> int:
    checks = [bool(user.first_name), bool(user.last_name), bool(user.email)]
    if analyst_profile is not None:
        checks.extend(
            [
                bool(analyst_profile.display_name),
                bool(analyst_profile.bio),
                bool(analyst_profile.avatar),
            ]
        )
    if not checks:
        return 0
    return round(sum(checks) / len(checks) * 100)


@login_required
@require_http_methods(["GET", "POST"])
def profile(request):
    analyst_profile = _get_analyst_profile(request.user)
    user_form = UserProfileForm(request.POST or None, instance=request.user)
    analyst_form = None

    allowed_tabs = {"profile", "following"}
    if request.user.role == User.Role.ANALYST:
        allowed_tabs.update({"predictions", "followers"})

    active_tab = request.GET.get("tab", "profile")
    if active_tab not in allowed_tabs:
        active_tab = "profile"

    if analyst_profile is not None:
        analyst_form = AnalystProfileForm(
            request.POST or None,
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

    followers_count = (
        request.user.analyst_followers.count()
        if request.user.role == User.Role.ANALYST
        else 0
    )
    following_count = request.user.analyst_follows.count()
    following_ids = set(
        request.user.analyst_follows.values_list("analyst_id", flat=True)
    )
    followers = (
        AnalystFollow.objects.filter(analyst=request.user)
        .select_related("follower", "follower__analyst_profile")
        if request.user.role == User.Role.ANALYST
        else AnalystFollow.objects.none()
    )
    following = AnalystFollow.objects.filter(follower=request.user).select_related(
        "analyst",
        "analyst__analyst_profile",
    )

    context = {
        "analyst_profile": analyst_profile,
        "user_form": user_form,
        "analyst_form": analyst_form,
        "active_tab": active_tab,
        "followers_count": followers_count,
        "following_count": following_count,
        "followers": followers,
        "following": following,
        "following_ids": following_ids,
        "predictions_count": 0,
        "profile_completion": _profile_completion(request.user, analyst_profile),
    }
    return render(request, "cabinet/profile.html", context)


@login_required
def legacy_profile_edit(request):
    return redirect("cabinet:profile")


@login_required
@require_POST
def upload_avatar(request):
    analyst_profile = _get_analyst_profile(request.user)
    if analyst_profile is None:
        return JsonResponse(
            {"ok": False, "error": "Аватар аналитика недоступен для этого типа аккаунта."},
            status=400,
        )

    form = AnalystAvatarForm(request.POST, request.FILES, instance=analyst_profile)
    if not form.is_valid():
        errors = form.errors.get("avatar") or form.non_field_errors()
        message = errors[0] if errors else "Не удалось загрузить изображение."
        return JsonResponse({"ok": False, "error": str(message)}, status=400)

    previous_avatar = analyst_profile.avatar.name if analyst_profile.avatar else None
    profile = form.save()

    if previous_avatar and previous_avatar != profile.avatar.name:
        storage = profile.avatar.storage
        if storage.exists(previous_avatar):
            storage.delete(previous_avatar)

    return JsonResponse(
        {
            "ok": True,
            "avatar_url": profile.avatar.url,
            "message": "Аватар обновлён.",
        }
    )


@login_required
@require_POST
def follow_analyst(request, user_id):
    analyst = get_object_or_404(User, pk=user_id, role=User.Role.ANALYST)
    if analyst.pk == request.user.pk:
        return JsonResponse(
            {"ok": False, "error": "Нельзя подписаться на самого себя."},
            status=400,
        )

    AnalystFollow.objects.get_or_create(
        follower=request.user,
        analyst=analyst,
    )
    return JsonResponse({"ok": True, "message": "Вы подписаны."})
