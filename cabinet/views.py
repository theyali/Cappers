from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from game.models import PredictionCoupon
from notifications.models import TelegramAccount
from notifications.services import get_preferences
from notifications.telegram_bot import get_bot_token
from wallets.models import (
    BalanceTransaction,
    CopiedBet,
    CopyBettingSubscription,
    RealBalanceTransaction,
)
from wallets.services import ensure_real_balance, ensure_virtual_balance, format_money

from .achievements import build_achievement_overview
from .dashboard_views import build_dashboard_context
from .forms import (
    AnalystAvatarForm,
    AnalystProfileForm,
    RegistrationForm,
    UserProfileForm,
)
from .models import AnalystFollow, AnalystProfile, User
from .paid_predictions import (
    profile_paid_predictions_enabled,
    subscribe_to_paid_predictions,
    user_can_view_paid_predictions,
)


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


def _coupon_result(coupon) -> tuple[str, str]:
    if coupon.published_status == PredictionCoupon.PublishedStatus.CANCELED:
        return "canceled", "Отменен"
    if coupon.published_status == PredictionCoupon.PublishedStatus.DRAFT:
        return "draft", "Черновик"
    if coupon.state_status == PredictionCoupon.StateStatus.WIN:
        return "won", "Выиграл"
    if coupon.state_status == PredictionCoupon.StateStatus.LOSE:
        return "lost", "Проиграл"
    if coupon.state_status == PredictionCoupon.StateStatus.REFUND:
        return "refund", "Возврат"
    return "pending", "Ожидает"


def _coupon_total_coefficient(predictions) -> str:
    if not predictions:
        return "—"

    total = 1
    for prediction in predictions:
        total *= prediction.coefficient
    return format(total, ".3f")


@login_required
@require_http_methods(["GET", "POST"])
def profile(request):
    analyst_profile = _get_analyst_profile(request.user)
    user_form = UserProfileForm(request.POST or None, instance=request.user)
    analyst_form = None

    allowed_tabs = {"profile", "following", "settings", "achievements", "wallet", "copybetting"}
    if request.user.role == User.Role.ANALYST:
        allowed_tabs.update({"predictions", "followers"})

    active_tab = request.GET.get("tab", "profile")
    if active_tab not in allowed_tabs:
        active_tab = "profile"

    if analyst_profile is not None:
        analyst_form = AnalystProfileForm(request.POST or None, instance=analyst_profile)

    if request.method == "POST":
        user_is_valid = user_form.is_valid()
        analyst_is_valid = analyst_form.is_valid() if analyst_form is not None else True

        if user_is_valid and analyst_is_valid:
            with transaction.atomic():
                user_form.save()
                if analyst_form is not None:
                    analyst_form.save()
            messages.success(request, "Профиль обновлён.")
            return redirect(f"{reverse('cabinet:profile')}?tab=settings")
        active_tab = "settings"

    followers_count = request.user.analyst_followers.count() if request.user.role == User.Role.ANALYST else 0
    following_count = request.user.analyst_follows.count()
    following_ids = set(request.user.analyst_follows.values_list("analyst_id", flat=True))
    followers = (
        AnalystFollow.objects.filter(analyst=request.user)
        .select_related("follower", "follower__analyst_profile")
        if request.user.role == User.Role.ANALYST
        else AnalystFollow.objects.none()
    )
    following = AnalystFollow.objects.filter(follower=request.user).select_related(
        "analyst", "analyst__analyst_profile"
    )
    notification_preferences = get_preferences(request.user)
    telegram_account = TelegramAccount.objects.filter(user=request.user).first()
    virtual_balance = ensure_virtual_balance(request.user)
    real_balance = ensure_real_balance(request.user) if request.user.role == User.Role.ANALYST else None
    virtual_transactions = BalanceTransaction.objects.filter(user=request.user).order_by("-created_at", "-id")[:20]
    real_transactions = (
        RealBalanceTransaction.objects.filter(user=request.user).order_by("-created_at", "-id")[:20]
        if request.user.role == User.Role.ANALYST
        else []
    )
    copybetting_subscriptions = (
        CopyBettingSubscription.objects.filter(user=request.user)
        .select_related("analyst", "analyst__analyst_profile")
        .prefetch_related("allowed_sports")
        .order_by("-started_at", "-id")
    )
    copied_bets = (
        CopiedBet.objects.filter(user=request.user)
        .select_related("analyst", "analyst__analyst_profile", "source_coupon")
        .order_by("-created_at", "-id")[:20]
    )

    my_coupons = []
    coupons_count = 0
    predictions_count = 0
    if request.user.role == User.Role.ANALYST:
        my_coupons = list(
            PredictionCoupon.objects.filter(author=request.user)
            .annotate(predictions_count=Count("predictions", distinct=True))
            .order_by("-created_at", "-id")
        )
        for coupon in my_coupons:
            coupon.result_key, coupon.result_label = _coupon_result(coupon)

        coupons_count = len(my_coupons)
        predictions_count = coupons_count

    achievement_overview = build_achievement_overview(
        request.user,
        followers_count=followers_count,
        is_verified=bool(analyst_profile and analyst_profile.is_verified),
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
        "my_coupons": my_coupons,
        "coupons_count": coupons_count,
        "predictions_count": predictions_count,
        "achievement_overview": achievement_overview,
        "profile_completion": _profile_completion(request.user, analyst_profile),
        "notification_preferences": notification_preferences,
        "telegram_account": telegram_account,
        "telegram_bot_configured": bool(get_bot_token()),
        "virtual_balance": virtual_balance,
        "virtual_balance_display": format_money(virtual_balance.balance),
        "real_balance": real_balance,
        "real_balance_display": format_money(real_balance.balance) if real_balance else "",
        "real_pending_withdrawal_display": format_money(real_balance.pending_withdrawal) if real_balance else "",
        "virtual_transactions": virtual_transactions,
        "real_transactions": real_transactions,
        "copybetting_subscriptions": copybetting_subscriptions,
        "copied_bets": copied_bets,
    }
    if request.user.role == User.Role.ANALYST:
        context.update(build_dashboard_context(request.user))

    return render(request, "cabinet/profile.html", context)


@login_required
@require_GET
def achievement_stats(request):
    analyst_profile = _get_analyst_profile(request.user)
    followers_count = request.user.analyst_followers.count() if request.user.is_analyst else 0
    overview = build_achievement_overview(
        request.user,
        followers_count=followers_count,
        is_verified=bool(analyst_profile and analyst_profile.is_verified),
    )
    return JsonResponse(
        {
            "ok": True,
            "is_analyst": request.user.is_analyst,
            "unlocked_count": overview["unlocked_count"],
            "total_count": overview["total_count"],
            "completion_percent": overview["completion_percent"],
            "next_achievement": overview["next_achievement"],
            "items": overview["items"],
        }
    )


@login_required
@require_GET
def following_summary(request):
    follows = (
        AnalystFollow.objects.filter(follower=request.user)
        .select_related("analyst", "analyst__analyst_profile")
        .annotate(
            predictions_count=Count(
                "analyst__prediction_coupons",
                filter=Q(
                    analyst__prediction_coupons__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
                    analyst__prediction_coupons__is_paid=False,
                ),
                distinct=True,
            ),
            followers_count=Count("analyst__analyst_followers", distinct=True),
        )
        .order_by("-created_at")
    )

    items = []
    for follow in follows:
        analyst = follow.analyst
        profile = getattr(analyst, "analyst_profile", None)
        display_name = (
            profile.display_name
            if profile and profile.display_name
            else analyst.get_full_name() or analyst.username
        )
        items.append(
            {
                "username": analyst.username,
                "display_name": display_name,
                "specialization": profile.specialization if profile else "",
                "avatar_url": profile.avatar.url if profile and profile.avatar else "",
                "is_verified": bool(profile and profile.is_verified),
                "predictions_count": follow.predictions_count,
                "followers_count": follow.followers_count,
                "joined_at": analyst.date_joined.isoformat(),
                "url": reverse("front:expert_profile", kwargs={"username": analyst.username}),
            }
        )

    return JsonResponse({"ok": True, "items": items})


@login_required
def coupon_detail(request, coupon_id: int):
    coupon = get_object_or_404(
        PredictionCoupon.objects.filter(author=request.user).prefetch_related(
            "predictions__match__sport",
            "predictions__match__league",
            "predictions__match__home_team",
            "predictions__match__away_team",
        ),
        pk=coupon_id,
    )
    predictions = list(coupon.predictions.all())

    return render(
        request,
        "cabinet/coupon_detail.html",
        {
            "coupon": coupon,
            "predictions": predictions,
            "coupon_total_coefficient": _coupon_total_coefficient(predictions),
        },
    )


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

    return JsonResponse({"ok": True, "avatar_url": profile.avatar.url, "message": "Аватар обновлён."})


@login_required
@require_POST
def follow_analyst(request, user_id):
    analyst = get_object_or_404(
        User.objects.select_related("analyst_profile"),
        pk=user_id,
        role=User.Role.ANALYST,
    )
    if analyst.pk == request.user.pk:
        return JsonResponse({"ok": False, "error": "Нельзя подписаться на самого себя."}, status=400)
    if profile_paid_predictions_enabled(analyst) and not user_can_view_paid_predictions(
        request.user,
        analyst,
    ):
        return JsonResponse(
            {
                "ok": False,
                "payment_required": True,
                "payment_url": reverse("cabinet:paid_predictions_subscribe", args=[analyst.pk]),
                "error": "Этот каппер перешёл на платные прогнозы. Оформите платную подписку.",
            },
            status=402,
        )

    AnalystFollow.objects.get_or_create(follower=request.user, analyst=analyst)
    return JsonResponse({"ok": True, "message": "Вы подписаны."})


@login_required
@require_POST
def decline_paid_predictions_view(request, user_id):
    analyst = get_object_or_404(User, pk=user_id, role=User.Role.ANALYST)
    if analyst.pk != request.user.pk:
        AnalystFollow.objects.filter(follower=request.user, analyst=analyst).delete()
        messages.success(request, "Вы отписались от каппера.")

    next_url = request.POST.get("next") or request.META.get("HTTP_REFERER") or ""
    if not url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        next_url = reverse("front:following_feed")
    return redirect(next_url)


@login_required
@require_http_methods(["GET", "POST"])
def subscribe_paid_predictions_view(request, user_id):
    analyst = get_object_or_404(
        User.objects.select_related("analyst_profile"),
        pk=user_id,
        role=User.Role.ANALYST,
    )
    profile = getattr(analyst, "analyst_profile", None)
    expert_url = reverse("front:expert_profile", kwargs={"username": analyst.username})
    raw_next_url = (
        request.POST.get("next")
        if request.method == "POST"
        else request.GET.get("next")
    ) or request.META.get("HTTP_REFERER") or expert_url
    if not url_has_allowed_host_and_scheme(
        raw_next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        raw_next_url = expert_url

    if not profile or not profile_paid_predictions_enabled(analyst):
        messages.error(request, "Этот эксперт не публикует платные прогнозы.")
        return redirect(expert_url)

    if request.method == "GET":
        return render(
            request,
            "cabinet/paid_predictions_checkout.html",
            {
                "expert": analyst,
                "analyst_profile": profile,
                "expert_name": profile.display_name or analyst.get_full_name() or analyst.username,
                "next_url": raw_next_url,
            },
        )

    try:
        subscription = subscribe_to_paid_predictions(request.user, analyst)
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            f"Платная подписка активна до {subscription.expires_at:%d.%m.%Y}.",
        )
    return redirect(raw_next_url)
