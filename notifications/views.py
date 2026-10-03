from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from game.models import Match

from .models import MatchWatch, Notification, NotificationSectionState, TelegramAccount
from .services import (
    clear_section_states,
    decrement_section_state,
    get_preferences,
    notification_kinds_for_section,
    refresh_section_state,
    section_badge_payload,
)
from .telegram_bot import build_connect_url, disconnect_telegram, get_bot_token


PAGE_SIZE = 30
SUMMARY_BATCH_SIZE = 12


def _avatar_url(user) -> str:
    return user.avatar.url if getattr(user, "avatar", None) else ""


def _in_app_notifications_queryset(user):
    if not get_preferences(user).in_app_enabled:
        return Notification.objects.none()
    return Notification.objects.filter(
        recipient=user,
        show_in_app=True,
    )


@login_required
def center(request):
    active_filter = request.GET.get("filter", "all")
    if active_filter not in {"all", "unread"}:
        active_filter = "all"

    queryset = _in_app_notifications_queryset(request.user).select_related("actor")
    if active_filter == "unread":
        queryset = queryset.filter(is_read=False)

    paginator = Paginator(queryset, PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))
    preferences = get_preferences(request.user)
    telegram_account = TelegramAccount.objects.filter(user=request.user).first()
    unread_count = _in_app_notifications_queryset(request.user).filter(is_read=False).count()
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
    queryset = _in_app_notifications_queryset(request.user)
    unread_count = queryset.filter(is_read=False).count()
    section_payload = section_badge_payload(request.user)
    latest_id = (
        Notification.objects.filter(recipient=request.user)
        .order_by("-id")
        .values_list("id", flat=True)
        .first()
        or 0
    )

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
            pending_queryset = queryset.filter(id__gt=after_id)
            if pending_queryset.count() > SUMMARY_BATCH_SIZE:
                return JsonResponse(
                    {
                        "ok": True,
                        "unread_count": unread_count,
                        "section_badges": section_payload["badges"],
                        "section_counts": section_payload["counts"],
                        "avatar_url": _avatar_url(request.user),
                        "latest_id": latest_id,
                        "cursor_id": latest_id,
                        "notifications": [],
                    }
                )
            new_notifications = list(
                pending_queryset.order_by("id")[:SUMMARY_BATCH_SIZE]
            )
            items = [
                {
                    "id": notification.id,
                    "kind": notification.kind,
                    "title": notification.title,
                    "message": notification.message,
                    "url": notification.url,
                    "image_url": notification.meta.get("image_url", ""),
                    "created_at": notification.created_at.isoformat(),
                }
                for notification in new_notifications
            ]
            cursor_id = new_notifications[-1].id if new_notifications else latest_id

    return JsonResponse(
        {
            "ok": True,
            "unread_count": unread_count,
            "section_badges": section_payload["badges"],
            "section_counts": section_payload["counts"],
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
        "prediction_like",
        "prediction_favorite",
        "copybetting",
        "new_follower",
        "paid_subscription",
        "new_prediction",
        "requested_match_prediction",
        "match_prediction",
        "tournament_started",
        "tournament_finished",
        "own_coupon_settled",
        "favorite_settled",
        "match_reminder",
        "achievement",
        "bonus_daily_task",
        "bonus_streak",
        "bonus_level",
        "bonus_roulette",
        "bonus_referral",
    )
    for field in checkbox_fields:
        setattr(preferences, field, field in request.POST)

    preferences.telegram_enabled = bool(
        preferences.telegram_chat_id and "telegram_enabled" in request.POST
    )
    preferences.save()
    if not preferences.in_app_enabled:
        clear_section_states(request.user)
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "message": "Настройки уведомлений сохранены."})
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
        _in_app_notifications_queryset(request.user),
        pk=notification_id,
    )
    was_unread = not notification.is_read
    notification.mark_read()
    if was_unread:
        decrement_section_state(notification)
    section_payload = section_badge_payload(request.user)
    return JsonResponse(
        {
            "ok": True,
            "section_badges": section_payload["badges"],
            "section_counts": section_payload["counts"],
        }
    )


@login_required
@require_POST
def mark_all_read(request):
    now = timezone.now()
    updated = _in_app_notifications_queryset(request.user).filter(
        is_read=False,
    ).update(is_read=True, read_at=now)
    if updated:
        clear_section_states(request.user)
    section_payload = section_badge_payload(request.user)
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse(
            {
                "ok": True,
                "updated": updated,
                "section_badges": section_payload["badges"],
                "section_counts": section_payload["counts"],
            }
        )
    return redirect("notifications:center")


@login_required
@require_POST
def mark_section_read(request, section: str):
    valid_sections = {
        choice for choice, _label in NotificationSectionState.Section.choices
    }
    if section not in valid_sections:
        return JsonResponse({"ok": False, "error": "Неизвестный раздел."}, status=404)

    kinds = notification_kinds_for_section(section)
    now = timezone.now()
    updated = 0
    if kinds:
        updated = _in_app_notifications_queryset(request.user).filter(
            is_read=False,
            kind__in=kinds,
        ).update(is_read=True, read_at=now)
    refresh_section_state(request.user, section)
    section_payload = section_badge_payload(request.user)
    unread_count = (
        _in_app_notifications_queryset(request.user).filter(is_read=False).count()
    )
    return JsonResponse(
        {
            "ok": True,
            "updated": updated,
            "unread_count": unread_count,
            "section_badges": section_payload["badges"],
            "section_counts": section_payload["counts"],
        }
    )


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
