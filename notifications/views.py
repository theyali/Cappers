from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from cabinet.models import AnalystProfile
from game.models import Match

from .models import MatchWatch, Notification, TelegramAccount
from .services import get_preferences
from .telegram_bot import build_connect_url, disconnect_telegram, get_bot_token


PAGE_SIZE = 30
SUMMARY_BATCH_SIZE = 12


def _avatar_url(user) -> str:
    if user.is_analyst:
        try:
            profile = user.analyst_profile
        except AnalystProfile.DoesNotExist:
            profile = None
        if profile and profile.avatar:
            return profile.avatar.url
    return user.avatar.url if getattr(user, "avatar", None) else ""


@login_required
def center(request):
    active_filter = request.GET.get("filter", "all")
    if active_filter not in {"all", "unread"}:
        active_filter = "all"

    queryset = Notification.objects.filter(
        recipient=request.user,
        show_in_app=True,
    ).select_related("actor")
    if active_filter == "unread":
        queryset = queryset.filter(is_read=False)

    paginator = Paginator(queryset, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))
    preferences = get_preferences(request.user)
    telegram_account = TelegramAccount.objects.filter(user=request.user).first()
    unread_count = Notification.objects.filter(
        recipient=request.user,
        show_in_app=True,
        is_read=False,
    ).count()
    watched_matches = (
        MatchWatch.objects.filter(
            user=request.user,
            match__starts_at__gte=timezone.now(),
        )
        .select_related("match__home_team", "match__away_team", "match__league")
        .order_by("match__starts_at")[:8]
    )

    return render(
        request,
        "notifications/center.html",
        {
            "page_obj": page_obj,
            "preferences": preferences,
            "telegram_account": telegram_account,
            "active_filter": active_filter,
            "unread_count": unread_count,
            "watched_matches": watched_matches,
            "telegram_bot_configured": bool(get_bot_token()),
        },
    )


@login_required
@require_GET
def summary(request):
    queryset = Notification.objects.filter(
        recipient=request.user,
        show_in_app=True,
    )
    unread_count = queryset.filter(is_read=False).count()
    latest_id = queryset.order_by("-id").values_list("id", flat=True).first() or 0

    raw_after_id = request.GET.get("after_id")
    after_id = None
    if raw_after_id not in {None, ""}:
        try:
            after_id = max(0, int(raw_after_id))
        except (TypeError, ValueError):
            after_id = 0

    items = []
    cursor_id = latest_id
    if after_id is not None:
        if after_id > latest_id:
            cursor_id = latest_id
        else:
            new_notifications = list(
                queryset.filter(id__gt=after_id)
                .order_by("id")[:SUMMARY_BATCH_SIZE]
            )
            items = [
                {
                    "id": notification.id,
                    "kind": notification.kind,
                    "title": notification.title,
                    "message": notification.message,
                    "url": notification.url,
                    "created_at": notification.created_at.isoformat(),
                }
                for notification in new_notifications
            ]
            cursor_id = new_notifications[-1].id if new_notifications else latest_id

    return JsonResponse(
        {
            "ok": True,
            "unread_count": unread_count,
            "avatar_url": _avatar_url(request.user),
            "latest_id": latest_id,
            "cursor_id": cursor_id,
            "notifications": items,
        }
    )


@login_required
@require_POST
def update_preferences(request):
    preferences = get_preferences(request.user)
    checkbox_fields = (
        "in_app_enabled",
        "email_enabled",
        "new_prediction",
        "favorite_settled",
        "match_reminder",
        "achievement",
        "match_prediction",
    )
    for field in checkbox_fields:
        setattr(preferences, field, field in request.POST)

    preferences.telegram_enabled = bool(
        preferences.telegram_chat_id and "telegram_enabled" in request.POST
    )
    preferences.save()
    return redirect("notifications:center")


@login_required
@require_GET
def telegram_connect(request):
    if not get_bot_token():
        messages.error(request, "Telegram-бот ещё не настроен на сервере.")
        return redirect("notifications:center")

    try:
        connect_url = build_connect_url(request.user)
    except Exception:
        messages.error(request, "Не удалось связаться с Telegram. Попробуйте ещё раз.")
        return redirect("notifications:center")

    return redirect(connect_url)


@login_required
@require_POST
def telegram_disconnect(request):
    disconnect_telegram(request.user)
    messages.success(request, "Telegram отключён от аккаунта.")
    return redirect("notifications:center")


@login_required
@require_POST
def mark_read(request, notification_id: int):
    notification = get_object_or_404(
        Notification,
        pk=notification_id,
        recipient=request.user,
        show_in_app=True,
    )
    notification.mark_read()
    return JsonResponse({"ok": True})


@login_required
@require_POST
def mark_all_read(request):
    now = timezone.now()
    updated = Notification.objects.filter(
        recipient=request.user,
        show_in_app=True,
        is_read=False,
    ).update(is_read=True, read_at=now)
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "updated": updated})
    return redirect("notifications:center")


@login_required
@require_http_methods(["GET", "POST"])
def match_watch(request, match_id: int):
    match = get_object_or_404(Match, pk=match_id)
    watch = MatchWatch.objects.filter(user=request.user, match=match).first()

    if request.method == "GET":
        return JsonResponse({"ok": True, "watching": watch is not None})

    if watch:
        watch.delete()
        watching = False
    else:
        MatchWatch.objects.create(user=request.user, match=match)
        watching = True
    return JsonResponse({"ok": True, "watching": watching})
