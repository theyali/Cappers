from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from cabinet.models import User

from .forms import BotAccountProfileForm
from .models import BotAccount


def _ensure_bot_admin(user) -> None:
    if not (user.is_staff or user.is_superuser):
        raise PermissionDenied


def _avatar_url(bot_account: BotAccount) -> str:
    user = bot_account.user
    if user.role == User.Role.ANALYST:
        analyst_profile = getattr(user, "analyst_profile", None)
        if analyst_profile is not None and analyst_profile.avatar:
            return analyst_profile.avatar.url

    if user.avatar:
        return user.avatar.url
    return ""


def _resolve_posted_bot(bots, raw_bot_id):
    bot_id = str(raw_bot_id or "").strip()
    if not bot_id.isdigit():
        raise Http404
    return get_object_or_404(bots, pk=int(bot_id))


@login_required
@require_http_methods(["GET", "POST"])
def manage_accounts(request):
    _ensure_bot_admin(request.user)

    bots_queryset = (
        BotAccount.objects.select_related("user", "user__analyst_profile")
        .order_by("kind", "user__username")
    )
    bots = list(bots_queryset)

    submitted_bot = None
    submitted_form = None

    if request.method == "POST":
        submitted_bot = _resolve_posted_bot(bots_queryset, request.POST.get("bot_id"))
        submitted_form = BotAccountProfileForm(
            request.POST,
            request.FILES,
            instance=submitted_bot.user,
            bot_account=submitted_bot,
            prefix=f"bot-{submitted_bot.pk}",
        )

        if submitted_form.is_valid():
            submitted_form.save()
            messages.success(
                request,
                f"Данные бота @{submitted_bot.user.username} обновлены.",
            )
            return redirect("bots:manage_accounts")

    bot_rows = []
    for bot in bots:
        if submitted_bot is not None and bot.pk == submitted_bot.pk:
            form = submitted_form
        else:
            form = BotAccountProfileForm(
                instance=bot.user,
                bot_account=bot,
                prefix=f"bot-{bot.pk}",
            )

        bot_rows.append(
            {
                "bot": bot,
                "form": form,
                "avatar_url": _avatar_url(bot),
            }
        )

    return render(
        request,
        "bots/manage_accounts.html",
        {
            "bot_rows": bot_rows,
            "bots_count": len(bot_rows),
            "bots_admin_active": True,
        },
    )
