from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from django.views.decorators.cache import never_cache

from cabinet.models import AnalystProfile

from .forms import BotAccountDetailsForm, BotAccountProfileForm, BotPublicProfileForm, BotSettingsForm
from .models import BotAccount


def _ensure_bot_admin(user) -> None:
    if not (user.is_staff or user.is_superuser):
        raise PermissionDenied


def _avatar_url(bot_account: BotAccount) -> str:
    user = bot_account.user
    if user.avatar:
        return user.avatar.url
    return ""


def _resolve_posted_bot(bots, raw_bot_id):
    bot_id = str(raw_bot_id or "").strip()
    if not bot_id.isdigit():
        raise Http404
    return get_object_or_404(bots, pk=int(bot_id))


def _bot_queryset():
    return BotAccount.objects.select_related("user", "user__analyst_profile")


@login_required
@require_http_methods(["GET", "POST"])
def manage_accounts(request):
    _ensure_bot_admin(request.user)

    bots_queryset = _bot_queryset().order_by("kind", "user__username")
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
            "page_class":"profile",
            "bot_rows": bot_rows,
            "bots_count": len(bot_rows),
            "bots_admin_active": True,
        },
    )


@login_required
@never_cache
@require_http_methods(["GET", "POST"])
def edit_account(request, bot_id: int):
    _ensure_bot_admin(request.user)
    bot = get_object_or_404(_bot_queryset(), pk=bot_id)
    profile = getattr(bot.user, "analyst_profile", None) or AnalystProfile(user=bot.user)
    data = request.POST if request.method == "POST" else None
    user_form = BotAccountDetailsForm(
        data, request.FILES or None, instance=bot.user, bot_account=bot, prefix="account",
    )
    profile_form = BotPublicProfileForm(data, instance=profile, prefix="profile")
    settings_form = BotSettingsForm(data, instance=bot, prefix="bot")
    forms = (user_form, profile_form, settings_form)
    if request.method == "POST" and all([form.is_valid() for form in forms]):
        with transaction.atomic():
            profile_form.save()
            user_form.save()
            settings_form.save()
        messages.success(request, f"Профиль бота @{bot.user.username} обновлён.")
        return redirect("bots:manage_accounts")
    return render(request, "bots/edit_account.html", {
        "page_class": "profile", "bots_admin_active": True, "bot": bot,
        "user_form": user_form, "profile_form": profile_form, "settings_form": settings_form,
        "avatar_url": _avatar_url(bot),
        "field_sections": [
            {"title": "Данные аккаунта", "fields": [user_form[name] for name in (
                "username", "first_name", "last_name", "gender", "country", "email", "telegram_username",
            )]},
            {"title": "Профиль и описание", "fields": [profile_form[name] for name in (
                "display_name", "specialization", "bio", "favorite_sports", "favorite_leagues",
            )]},
            {"title": "Социальные сети", "fields": [profile_form[name] for name in (
                "telegram_channel", "telegram_account", "instagram", "threads", "youtube", "tiktok", "facebook", "x",
            )]},
        ],
        "status_fields": [settings_form["is_active"], *[profile_form[name] for name in (
            "is_public", "is_verified", "is_recommended",
        )]],
    })


@login_required
@require_http_methods(["POST"])
def upload_avatar(request, bot_id: int):
    _ensure_bot_admin(request.user)

    bot = get_object_or_404(_bot_queryset(), pk=bot_id)
    upload = request.FILES.get("avatar")
    if upload is None:
        return JsonResponse(
            {"ok": False, "error": "Выберите изображение."},
            status=400,
        )

    form = BotAccountProfileForm(
        {
            "username": bot.user.username,
            "first_name": bot.user.first_name,
            "last_name": bot.user.last_name,
        },
        {"avatar": upload},
        instance=bot.user,
        bot_account=bot,
    )

    if not form.is_valid():
        avatar_errors = form.errors.get("avatar")
        if avatar_errors:
            error = str(avatar_errors[0])
        else:
            error = "Не удалось загрузить изображение."
        return JsonResponse({"ok": False, "error": error}, status=400)

    user = form.save()
    return JsonResponse(
        {
            "ok": True,
            "avatar_url": user.avatar.url,
            "message": "Изображение обновлено.",
        }
    )
