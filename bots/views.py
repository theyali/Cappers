from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from cabinet.models import User

from .forms import BotAccountProfileForm
from .models import BotAccount


def _ensure_bot_admin(user) -> None:
    if not (user.is_staff or user.is_superuser):
        raise PermissionDenied


def _avatar_url(bot_account: BotAccount | None) -> str:
    if bot_account is None:
        return ""

    user = bot_account.user
    if user.role == User.Role.ANALYST:
        analyst_profile = getattr(user, "analyst_profile", None)
        if analyst_profile is not None and analyst_profile.avatar:
            return analyst_profile.avatar.url

    if user.avatar:
        return user.avatar.url
    return ""


@login_required
@require_http_methods(["GET", "POST"])
def manage_accounts(request):
    _ensure_bot_admin(request.user)

    bots = (
        BotAccount.objects.select_related("user", "user__analyst_profile")
        .order_by("kind", "user__username")
    )

    selected_id = request.POST.get("bot_id") or request.GET.get("bot")
    selected_bot = None

    if selected_id:
        selected_id = str(selected_id).strip()
        if not selected_id.isdigit():
            raise Http404
        selected_bot = get_object_or_404(bots, pk=int(selected_id))
    else:
        selected_bot = bots.first()

    form = None
    if selected_bot is not None:
        form = BotAccountProfileForm(
            request.POST or None,
            request.FILES or None,
            instance=selected_bot.user,
            bot_account=selected_bot,
        )

        if request.method == "POST" and form.is_valid():
            form.save()
            messages.success(
                request,
                f"Данные бота @{selected_bot.user.username} обновлены.",
            )
            return redirect(
                f"{reverse('bots:manage_accounts')}?bot={selected_bot.pk}"
            )

    return render(
        request,
        "bots/manage_accounts.html",
        {
            "bots": bots,
            "bots_count": bots.count(),
            "selected_bot": selected_bot,
            "selected_avatar_url": _avatar_url(selected_bot),
            "form": form,
            "bots_admin_active": True,
        },
    )
