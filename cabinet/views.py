from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Max, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from front.models import PredictionFavorite, PredictionLike
from game.models import Country, PredictionCoupon, Sport
from notifications.models import Notification, NotificationSectionState, TelegramAccount
from notifications.services import get_preferences, refresh_section_state
from notifications.telegram_bot import get_bot_token
from wallets.models import (
    CoinTransaction,
    CopiedBet,
    CopyBettingSubscription,
    RealBalanceTransaction,
)
from wallets.services import ensure_coin_wallet, ensure_real_balance, format_coins, format_money
from wallets.services import InsufficientBalance

from .achievements import build_achievement_overview
from .dashboard_views import build_dashboard_context
from .earnings_views import build_earnings_context
from .forms import (
    AnalystPaidPlanSettingsForm,
    AnalystProfileForm,
    CapperArticleForm,
    MobileQuickAccessForm,
    RegistrationForm,
    AnalystAvatarForm,
    UserProfileForm,
)
from .capper_forms import CapperFocusForm
from .services.preferences import sync_user_sport_league_preferences
from .models import AnalystFollow, AnalystProfile, CapperArticle, DailyTask, User
from .paid_predictions import (
    get_active_paid_plans,
    profile_paid_predictions_enabled,
    subscribe_to_paid_predictions,
)
from .referrals import mark_referral_registration
from .services.bonus_center import build_profile_bonus_summary
from .services.capper_articles import (
    build_capper_articles_context,
    can_create_capper_article,
    can_edit_capper_article,
    save_capper_article,
    submit_capper_article_for_moderation,
)
from .services.daily_tasks import record_daily_task_action
from .vip import annotate_vip_status, attach_vip_status_to_user


WALLET_OPERATION_PAGE_SIZE = 20
FOLLOWING_NEW_PREDICTION_KINDS = (
    Notification.Kind.NEW_PREDICTION,
    Notification.Kind.REQUESTED_MATCH_PREDICTION,
)


def _error_message(exc) -> str:
    if isinstance(exc, ValidationError):
        return exc.messages[0] if exc.messages else str(exc)
    return str(exc)


def _ru_plural(value: int, one: str, few: str, many: str) -> str:
    value = abs(value)
    if value % 10 == 1 and value % 100 != 11:
        return one
    if 2 <= value % 10 <= 4 and not 12 <= value % 100 <= 14:
        return few
    return many


def _relative_time_ru(value) -> str:
    if not value:
        return ""

    delta = timezone.now() - value
    seconds = max(0, int(delta.total_seconds()))
    minutes = seconds // 60
    hours = minutes // 60
    days = hours // 24

    if days > 0:
        unit = _ru_plural(days, "день", "дня", "дней")
        return f"{days} {unit} назад"
    if hours > 0:
        unit = _ru_plural(hours, "час", "часа", "часов")
        return f"{hours} {unit} назад"
    if minutes > 0:
        unit = _ru_plural(minutes, "минуту", "минуты", "минут")
        return f"{minutes} {unit} назад"
    return "только что"


def _mark_notification_section_read(user, section: str, kinds: tuple[str, ...]) -> int:
    updated = Notification.objects.filter(
        recipient=user,
        kind__in=kinds,
        show_in_app=True,
        is_read=False,
    ).update(is_read=True, read_at=timezone.now())
    refresh_section_state(user, section)
    return updated


def _capper_article_action(request) -> str:
    return "draft" if request.POST.get("article_action") == "draft" else "submit"


def _add_form_validation_error(form, exc: ValidationError) -> None:
    if hasattr(exc, "message_dict"):
        for field, errors in exc.message_dict.items():
            form.add_error(field if field in form.fields else None, errors)
        return

    form.add_error(None, exc)


@login_required
def capper_articles(request):
    if not request.user.is_analyst:
        messages.info(request, "Сначала станьте каппером, чтобы работать со статьями.")
        return redirect("cabinet:become_capper")

    context = build_capper_articles_context(request.user)
    context["page"] = {
        "title": "Мои статьи — КапперХаб",
        "heading": "Мои статьи",
        "description": "Черновики, статьи на модерации и опубликованные материалы.",
        "mobile_nav_label": "Навигация кабинета",
        "profile_nav_label": "Разделы профиля",
    }
    return render(request, "cabinet/capper_articles.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def capper_article_create(request):
    if not request.user.is_analyst:
        messages.info(request, "Сначала станьте каппером, чтобы работать со статьями.")
        return redirect("cabinet:become_capper")
    if not can_create_capper_article(request.user):
        messages.info(request, "Стать VIP, чтобы публиковать статьи.")
        return redirect("cabinet:capper_articles")

    form = CapperArticleForm(request.POST or None, request.FILES or None)
    article = None
    if request.method == "POST" and form.is_valid():
        action = _capper_article_action(request)
        try:
            article = save_capper_article(
                request.user,
                form.cleaned_data,
                request.FILES,
            )
        except ValidationError as exc:
            _add_form_validation_error(form, exc)
        else:
            if action == "draft":
                messages.success(request, "Черновик статьи сохранён.")
                return redirect("cabinet:capper_article_edit", article_id=article.pk)

            try:
                submit_capper_article_for_moderation(request.user, article)
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages))
                return redirect("cabinet:capper_article_edit", article_id=article.pk)

            messages.success(request, "Статья отправлена на модерацию.")
            return redirect("cabinet:capper_articles")

    return render(
        request,
        "cabinet/capper_article_form.html",
        {
            "form": form,
            "article": article,
            "page_title": "Новая статья",
            "submit_label": "Отправить на модерацию",
            "active_tab": "articles",
            "can_submit_article": bool(article and can_edit_capper_article(request.user, article)),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def capper_article_edit(request, article_id):
    if not request.user.is_analyst:
        messages.info(request, "Сначала станьте каппером, чтобы работать со статьями.")
        return redirect("cabinet:become_capper")
    if not can_create_capper_article(request.user):
        messages.info(request, "Стать VIP, чтобы публиковать статьи.")
        return redirect("cabinet:capper_articles")

    article = get_object_or_404(
        CapperArticle,
        pk=article_id,
        author=request.user,
    )
    if not can_edit_capper_article(request.user, article):
        messages.info(request, "Редактировать можно только черновик или отклонённую статью.")
        return redirect("cabinet:capper_articles")

    form = CapperArticleForm(
        request.POST or None,
        request.FILES or None,
        instance=article,
    )

    if request.method == "POST" and form.is_valid():
        action = _capper_article_action(request)
        try:
            article = save_capper_article(
                request.user,
                form.cleaned_data,
                request.FILES,
                article=article,
            )
            if action == "submit":
                submit_capper_article_for_moderation(request.user, article)
        except ValidationError as exc:
            _add_form_validation_error(form, exc)
        else:
            if action == "draft":
                messages.success(request, "Черновик статьи сохранён.")
                return redirect("cabinet:capper_article_edit", article_id=article.pk)

            messages.success(request, "Статья отправлена на модерацию.")
            return redirect("cabinet:capper_articles")

    return render(
        request,
        "cabinet/capper_article_form.html",
        {
            "form": form,
            "article": article,
            "page_title": "Редактирование статьи",
            "submit_label": "Отправить на модерацию",
            "active_tab": "articles",
            "can_submit_article": can_edit_capper_article(request.user, article),
        },
    )


@login_required
@require_POST
def capper_article_submit(request, article_id):
    if not request.user.is_analyst:
        messages.info(request, "Сначала станьте каппером, чтобы работать со статьями.")
        return redirect("cabinet:become_capper")

    article = get_object_or_404(
        CapperArticle,
        pk=article_id,
        author=request.user,
    )
    try:
        submit_capper_article_for_moderation(request.user, article)
    except ValidationError as exc:
        messages.error(request, "; ".join(exc.messages))
        return redirect("cabinet:capper_article_edit", article_id=article.pk)

    messages.success(request, "Статья отправлена на модерацию.")
    return redirect("cabinet:capper_articles")


@require_http_methods(["GET", "POST"])
def register(request):
    if request.user.is_authenticated:
        return redirect("cabinet:profile")

    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = form.save()
            mark_referral_registration(request, user)
        login(request, user)
        messages.success(request, "Регистрация завершена.")
        return redirect("cabinet:profile")

    return render(request, "cabinet/auth/register.html", {"form": form, "page_class": "register"})


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
                bool(user.avatar),
            ]
        )
    if not checks:
        return 0
    return round(sum(checks) / len(checks) * 100)


def _verification_requirements(user, analyst_profile) -> dict:
    profile_completion = _profile_completion(user, analyst_profile)
    published = PredictionCoupon.objects.filter(
        author=user,
        published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
    )
    stats = published.aggregate(
        predictions=Count("id"),
        wins=Count("id", filter=Q(state_status=PredictionCoupon.StateStatus.WIN)),
    )
    likes_count = PredictionLike.objects.filter(
        prediction__author=user,
        prediction__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
    ).count()
    favorites_count = PredictionFavorite.objects.filter(
        prediction__author=user,
        prediction__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
    ).count()
    requirements = [
        {"label": "заполнить профиль", "done": profile_completion >= 100},
        {"label": "Первый прогноз", "done": (stats["predictions"] or 0) >= 1},
        {"label": "3 победы", "done": (stats["wins"] or 0) >= 3},
        {"label": "10 лайков", "done": likes_count >= 10},
        {"label": "10 сохранений", "done": favorites_count >= 10},
    ]
    missing = [item["label"] for item in requirements if not item["done"]]
    return {
        "can_request": not missing,
        "missing": missing,
        "missing_text": ", ".join(missing),
        "profile_completion": profile_completion,
    }


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


def _delete_expired_draft_coupons(user: User) -> int:
    max_age = max(int(getattr(settings, "SESSION_COOKIE_AGE", 1209600)), 1)
    cutoff = timezone.now() - timedelta(seconds=max_age)
    deleted, _ = PredictionCoupon.objects.filter(
        author=user,
        published_status=PredictionCoupon.PublishedStatus.DRAFT,
        updated_at__lt=cutoff,
    ).delete()
    return deleted


def _copybetting_audience_context(user) -> dict:
    if not getattr(user, "is_analyst", False):
        return {
            "copybetting_audience_subscriptions": [],
            "copybetting_audience_active_count": 0,
            "copybetting_audience_total_count": 0,
            "copybetting_audience_profit": 0,
            "copybetting_audience_profit_display": "0",
            "copybetting_audience_copied_bets_count": 0,
            "copybetting_audience_copied_bets": [],
        }

    audience_subscriptions = list(
        CopyBettingSubscription.objects.filter(analyst=user)
        .exclude(status=CopyBettingSubscription.Status.STOPPED)
        .select_related("user", "user__analyst_profile")
        .prefetch_related("allowed_sports")
        .annotate(copied_bets_count=Count("copied_bets", distinct=True))
        .order_by("status", "-updated_at", "-started_at", "-id")
    )
    all_audience = CopyBettingSubscription.objects.filter(analyst=user)
    active_count = all_audience.filter(status=CopyBettingSubscription.Status.ACTIVE).count()
    audience_profit = all_audience.aggregate(profit=Sum("total_profit"))["profit"] or 0
    audience_copied_bets_count = CopiedBet.objects.filter(analyst=user).count()

    return {
        "copybetting_audience_subscriptions": audience_subscriptions,
        "copybetting_audience_active_count": active_count,
        "copybetting_audience_total_count": all_audience.count(),
        "copybetting_audience_profit": audience_profit,
        "copybetting_audience_profit_display": format_coins(int(audience_profit)),
        "copybetting_audience_copied_bets_count": audience_copied_bets_count,
        "copybetting_audience_copied_bets": (
            CopiedBet.objects.filter(analyst=user)
            .select_related("user", "user__analyst_profile", "source_coupon")
            .order_by("-created_at", "-id")[:20]
        ),
    }


def _wallet_operation_cursor(operation) -> str:
    return f"{operation.created_at.isoformat()}|{operation.pk}"


def _parse_wallet_operation_cursor(raw_cursor: str):
    if not raw_cursor or "|" not in raw_cursor:
        return None

    raw_created_at, raw_pk = raw_cursor.rsplit("|", 1)
    created_at = parse_datetime(raw_created_at)
    if created_at is None:
        return None
    if timezone.is_naive(created_at):
        created_at = timezone.make_aware(created_at, timezone.get_current_timezone())

    try:
        pk = int(raw_pk)
    except (TypeError, ValueError):
        return None

    return created_at, pk


def _slice_wallet_operations(queryset, raw_cursor: str):
    cursor = _parse_wallet_operation_cursor(raw_cursor)
    if cursor is not None:
        created_at, pk = cursor
        queryset = queryset.filter(
            Q(created_at__lt=created_at)
            | Q(created_at=created_at, pk__lt=pk)
        )

    operations = list(queryset[: WALLET_OPERATION_PAGE_SIZE + 1])
    visible_operations = operations[:WALLET_OPERATION_PAGE_SIZE]
    has_next = len(operations) > WALLET_OPERATION_PAGE_SIZE
    next_cursor = _wallet_operation_cursor(visible_operations[-1]) if has_next and visible_operations else ""
    return visible_operations, next_cursor


def _wallet_history_response(
    request,
    *,
    operation_type: str,
    queryset,
    title: str,
    heading: str,
    description: str,
    kicker: str,
    empty_message: str,
    balance_label: str,
    balance_value: str,
):
    operations, next_cursor = _slice_wallet_operations(
        queryset.order_by("-created_at", "-id"),
        request.GET.get("cursor", ""),
    )
    operation_context = {
        "operation_items": operations,
        "operation_type": operation_type,
        "empty_message": empty_message,
    }

    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse(
            {
                "ok": True,
                "html": render_to_string(
                    "cabinet/includes/_wallet_operation_rows.html",
                    operation_context,
                    request=request,
                ),
                "next_cursor": next_cursor,
                "has_next": bool(next_cursor),
            }
        )

    analyst_profile = _get_analyst_profile(request.user)
    return render(
        request,
        "cabinet/wallet_operations.html",
        {
            "active_tab": "wallet",
            "analyst_profile": analyst_profile,
            "wallet_history_page": {
                "title": title,
                "heading": heading,
                "description": description,
                "kicker": kicker,
                "empty_message": empty_message,
                "balance_label": balance_label,
                "balance_value": balance_value,
                "back_url": f"{reverse('cabinet:profile')}?tab=wallet",
                "mobile_nav_label": "Навигация кабинета",
                "profile_nav_label": "Разделы профиля",
            },
            "operation_type": operation_type,
            "operation_items": operations,
            "empty_message": empty_message,
            "next_cursor": next_cursor,
            "page_class": "profile wallet-history-body",
        },
    )


@login_required
@require_GET
def coin_operations(request):
    coin_wallet = ensure_coin_wallet(request.user)
    return _wallet_history_response(
        request,
        operation_type="coins",
        queryset=CoinTransaction.objects.filter(user=request.user),
        title="Операции с коинами — КапперХаб",
        heading="Операции с коинами",
        description="История начислений и списаний коинов.",
        kicker="Коины",
        empty_message="Операций с коинами пока нет.",
        balance_label="Текущий баланс",
        balance_value=f"{format_coins(coin_wallet.balance)} коинов",
    )


@login_required
@require_GET
def real_operations(request):
    if request.user.role != User.Role.ANALYST:
        messages.info(request, "Реальные операции доступны только капперам.")
        return redirect(f"{reverse('cabinet:profile')}?tab=wallet")

    real_balance = ensure_real_balance(request.user)
    return _wallet_history_response(
        request,
        operation_type="real",
        queryset=RealBalanceTransaction.objects.filter(user=request.user),
        title="Реальные операции — КапперХаб",
        heading="Реальные операции",
        description="История пополнений, выводов и других операций.",
        kicker="Реальный баланс",
        empty_message="Реальных операций пока нет.",
        balance_label="Доступно",
        balance_value=f"{format_money(real_balance.balance)} ₽",
    )


@login_required
@require_http_methods(["GET", "POST"])
def profile(request):
    profile_settings_action = request.POST.get("profile_settings_action") if request.method == "POST" else ""
    is_mobile_quick_access_post = profile_settings_action == "mobile_quick_access"
    analyst_profile = _get_analyst_profile(request.user)
    profile_form_data = request.POST if request.method == "POST" and not is_mobile_quick_access_post else None
    user_form = UserProfileForm(profile_form_data, instance=request.user)
    analyst_form = None
    focus_form = None
    paid_plan_form = None
    mobile_quick_access_form = MobileQuickAccessForm(
        request.POST if is_mobile_quick_access_post else None,
        user=request.user,
    )

    allowed_tabs = {"profile", "following", "settings", "achievements", "wallet", "copybetting"}
    if request.user.role == User.Role.ANALYST:
        allowed_tabs.update({"predictions", "followers", "earnings"})

    active_tab = request.GET.get("tab", "profile")
    if active_tab not in allowed_tabs:
        active_tab = "profile"

    if analyst_profile is not None:
        analyst_form = AnalystProfileForm(profile_form_data, instance=analyst_profile)
        focus_form = CapperFocusForm(
            profile_form_data,
            initial={
                "sports": list(
                    request.user.sport_preferences.values_list("sport_id", flat=True)
                ),
                "leagues": list(
                    request.user.league_preferences.values_list("league_id", flat=True)
                ),
            },
        )
        paid_plan_form = AnalystPaidPlanSettingsForm(
            profile_form_data,
            analyst=request.user,
            prefix="paid_plans",
        )

    if request.method == "POST" and is_mobile_quick_access_post:
        if mobile_quick_access_form.is_valid():
            mobile_quick_access_form.save()
            messages.success(request, "Быстрый доступ обновлён.")
            return redirect(f"{reverse('cabinet:profile')}?tab=settings")
        active_tab = "settings"
    elif request.method == "POST":
        user_is_valid = user_form.is_valid()
        analyst_is_valid = analyst_form.is_valid() if analyst_form is not None else True
        focus_is_valid = focus_form.is_valid() if focus_form is not None else True
        paid_predictions_enabled = (
            bool(analyst_form.cleaned_data.get("paid_predictions_enabled"))
            if analyst_is_valid and analyst_form is not None
            else False
        )
        paid_plans_are_valid = (
            paid_plan_form.is_valid()
            if paid_plan_form is not None and paid_predictions_enabled
            else True
        )

        if user_is_valid and analyst_is_valid and focus_is_valid and paid_plans_are_valid:
            with transaction.atomic():
                user_form.save()
                if analyst_form is not None:
                    analyst_profile = analyst_form.save()
                if focus_form is not None:
                    sync_user_sport_league_preferences(
                        request.user,
                        focus_form.cleaned_data["sports"],
                        focus_form.cleaned_data["leagues"],
                        profile=analyst_profile,
                    )
                if paid_plan_form is not None and paid_predictions_enabled:
                    paid_plan_form.save(request.user)
            record_daily_task_action(
                request.user,
                DailyTask.TaskType.UPDATE_PROFILE,
                related_obj=request.user,
            )
            messages.success(request, "Профиль обновлён.")
            return redirect(f"{reverse('cabinet:profile')}?tab=settings")
        active_tab = "settings"

    followers_count = request.user.analyst_followers.count() if request.user.role == User.Role.ANALYST else 0
    following_count = request.user.analyst_follows.count()
    following_ids = set(request.user.analyst_follows.values_list("analyst_id", flat=True))
    followers = (
        annotate_vip_status(
            AnalystFollow.objects.filter(analyst=request.user).select_related(
                "follower",
                "follower__analyst_profile",
            ),
            user_outer_ref="follower_id",
        )
        if request.user.role == User.Role.ANALYST
        else AnalystFollow.objects.none()
    )
    following = annotate_vip_status(
        AnalystFollow.objects.filter(follower=request.user).select_related(
            "analyst",
            "analyst__analyst_profile",
        ).annotate(
            new_predictions_count=Count(
                "analyst__notification_actions",
                filter=Q(
                    analyst__notification_actions__recipient=request.user,
                    analyst__notification_actions__show_in_app=True,
                    analyst__notification_actions__is_read=False,
                    analyst__notification_actions__kind__in=FOLLOWING_NEW_PREDICTION_KINDS,
                ),
                distinct=True,
            ),
            latest_new_prediction_at=Max(
                "analyst__notification_actions__created_at",
                filter=Q(
                    analyst__notification_actions__recipient=request.user,
                    analyst__notification_actions__show_in_app=True,
                    analyst__notification_actions__is_read=False,
                    analyst__notification_actions__kind__in=FOLLOWING_NEW_PREDICTION_KINDS,
                ),
            ),
        ).order_by("-new_predictions_count", "-latest_new_prediction_at", "-created_at"),
        user_outer_ref="analyst_id",
    )
    notification_preferences = get_preferences(request.user)
    telegram_account = TelegramAccount.objects.filter(user=request.user).first()
    coin_wallet = ensure_coin_wallet(request.user)
    real_balance = ensure_real_balance(request.user) if request.user.role == User.Role.ANALYST else None
    coin_transactions = CoinTransaction.objects.filter(user=request.user).order_by("-created_at", "-id")[:20]
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

    earnings_context = {}
    active_paid_subscriber_ids = set()
    if request.user.role == User.Role.ANALYST:
        earnings_context = build_earnings_context(request.user)
        active_paid_subscriber_ids = {
            subscription.subscriber_id
            for subscription in earnings_context["active_paid_subscriptions"]
        }
    active_paid_subscribers = len(active_paid_subscriber_ids)

    unread_follower_ids = (
        set(
            Notification.objects.filter(
                recipient=request.user,
                kind=Notification.Kind.NEW_FOLLOWER,
                show_in_app=True,
                is_read=False,
                actor_id__isnull=False,
            ).values_list("actor_id", flat=True)
        )
        if request.user.role == User.Role.ANALYST
        else set()
    )
    for follow in followers:
        attach_vip_status_to_user(follow.follower, follow)
        follow.has_new_follower_notification = follow.follower_id in unread_follower_ids
    for follow in following:
        attach_vip_status_to_user(follow.analyst, follow)
        follow.latest_new_prediction_label = _relative_time_ru(
            follow.latest_new_prediction_at
        )
    following_new_analysts_count = sum(
        1 for follow in following if follow.new_predictions_count
    )
    if request.user.role == User.Role.ANALYST and active_tab == "followers":
        _mark_notification_section_read(
            request.user,
            NotificationSectionState.Section.FOLLOWERS,
            (Notification.Kind.NEW_FOLLOWER,),
        )

    my_coupons = []
    coupons_count = 0
    predictions_count = 0
    if request.user.role == User.Role.ANALYST:
        _delete_expired_draft_coupons(request.user)
        my_coupons = list(
            PredictionCoupon.objects.filter(author=request.user)
            .exclude(published_status=PredictionCoupon.PublishedStatus.DRAFT)
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

    verification_requirements = (
        _verification_requirements(request.user, analyst_profile)
        if request.user.role == User.Role.ANALYST and analyst_profile
        else None
    )
    profile_completion = (
        verification_requirements["profile_completion"]
        if verification_requirements
        else _profile_completion(request.user, analyst_profile)
    )
    profile_bonus_summary = (
        build_profile_bonus_summary(request.user)
        if active_tab == "profile"
        else None
    )

    context = {
        "analyst_profile": analyst_profile,
        "user_form": user_form,
        "analyst_form": analyst_form,
        "focus_form": focus_form,
        "paid_plan_form": paid_plan_form,
        "mobile_quick_access_form": mobile_quick_access_form,
        "active_tab": active_tab,
        "followers_count": followers_count,
        "following_count": following_count,
        "followers": followers,
        "following": following,
        "following_new_analysts_count": following_new_analysts_count,
        "following_ids": following_ids,
        "active_paid_subscribers": active_paid_subscribers,
        "active_paid_subscriber_ids": active_paid_subscriber_ids,
        "my_coupons": my_coupons,
        "coupons_count": coupons_count,
        "predictions_count": predictions_count,
        "achievement_overview": achievement_overview,
        "profile_completion": profile_completion,
        "verification_requirements": verification_requirements,
        "profile_bonus_summary": profile_bonus_summary,
        "notification_preferences": notification_preferences,
        "telegram_account": telegram_account,
        "telegram_bot_configured": bool(get_bot_token()),
        "coin_wallet": coin_wallet,
        "coin_balance_display": format_coins(coin_wallet.balance),
        "real_balance": real_balance,
        "real_balance_display": format_money(real_balance.balance) if real_balance else "",
        "real_pending_withdrawal_display": format_money(real_balance.pending_withdrawal) if real_balance else "",
        "coin_transactions": coin_transactions,
        "real_transactions": real_transactions,
        "copybetting_subscriptions": copybetting_subscriptions,
        "copied_bets": copied_bets,
        "page_class": "profile",
    }
    if focus_form is not None:
        context.update(
            {
                "league_picker_sports": Sport.objects.all().order_by("name_ru", "name"),
                "league_picker_countries": Country.objects.filter(
                    leagues__isnull=False
                ).distinct().order_by("name_ru", "name"),
                "league_search_url": reverse("cabinet:league_search"),
            }
        )
    context.update(_copybetting_audience_context(request.user))
    if request.user.role == User.Role.ANALYST:
        context.update(build_dashboard_context(request.user))
        context.update(earnings_context)

    return render(request, "cabinet/profile.html", context)


@login_required
@require_POST
def delete_account(request):
    if request.POST.get("confirmation") != "delete-account":
        messages.error(request, "Подтвердите удаление аккаунта.")
        return redirect(f"{reverse('cabinet:profile')}?tab=settings")

    user = request.user
    with transaction.atomic():
        user.delete()

    logout(request)
    messages.success(request, "Аккаунт и связанные данные удалены.")
    return redirect("front:index")


@login_required
@require_POST
def request_verification(request):
    analyst_profile = _get_analyst_profile(request.user)
    if analyst_profile is None:
        messages.error(request, "Проверка доступна только аналитикам.")
        return redirect(f"{reverse('cabinet:profile')}?tab=settings")
    if analyst_profile.is_verified:
        messages.info(request, "Профиль уже проверен.")
        return redirect(f"{reverse('cabinet:profile')}?tab=profile")

    requirements = _verification_requirements(request.user, analyst_profile)
    if not requirements["can_request"]:
        messages.error(
            request,
            f"Для проверки профиля нужно: {requirements['missing_text']}.",
        )
        return redirect(f"{reverse('cabinet:profile')}?tab=settings")

    if analyst_profile.verification_requested_at:
        messages.info(request, "Запрос проверки уже отправлен.")
    else:
        analyst_profile.verification_requested_at = timezone.now()
        analyst_profile.save(update_fields=["verification_requested_at", "updated_at"])
        messages.success(request, "Запрос проверки отправлен администраторам.")
    return redirect(f"{reverse('cabinet:profile')}?tab=profile")


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
                    analyst__prediction_coupons__audience=PredictionCoupon.Audience.FREE,
                ),
                distinct=True,
            ),
            followers_count=Count("analyst__analyst_followers", distinct=True),
            new_predictions_count=Count(
                "analyst__notification_actions",
                filter=Q(
                    analyst__notification_actions__recipient=request.user,
                    analyst__notification_actions__show_in_app=True,
                    analyst__notification_actions__is_read=False,
                    analyst__notification_actions__kind__in=FOLLOWING_NEW_PREDICTION_KINDS,
                ),
                distinct=True,
            ),
            latest_new_prediction_at=Max(
                "analyst__notification_actions__created_at",
                filter=Q(
                    analyst__notification_actions__recipient=request.user,
                    analyst__notification_actions__show_in_app=True,
                    analyst__notification_actions__is_read=False,
                    analyst__notification_actions__kind__in=FOLLOWING_NEW_PREDICTION_KINDS,
                ),
            ),
        )
        .order_by("-new_predictions_count", "-latest_new_prediction_at", "-created_at")
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
                "avatar_url": analyst.avatar.url if analyst.avatar else "",
                "is_verified": bool(profile and profile.is_verified),
                "predictions_count": follow.predictions_count,
                "followers_count": follow.followers_count,
                "new_predictions_count": follow.new_predictions_count,
                "latest_new_prediction_at": (
                    follow.latest_new_prediction_at.isoformat()
                    if follow.latest_new_prediction_at
                    else ""
                ),
                "latest_new_prediction_label": _relative_time_ru(
                    follow.latest_new_prediction_at
                ),
                "joined_at": analyst.date_joined.isoformat(),
                "url": reverse("front:expert_profile", kwargs={"username": analyst.username}),
            }
        )

    return JsonResponse({"ok": True, "items": items})


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

    form = AnalystAvatarForm(request.POST, request.FILES, instance=request.user)
    if not form.is_valid():
        errors = form.errors.get("avatar") or form.non_field_errors()
        message = errors[0] if errors else "Не удалось загрузить изображение."
        return JsonResponse({"ok": False, "error": str(message)}, status=400)

    previous_avatar = request.user.avatar.name if request.user.avatar else None
    user = form.save()

    if previous_avatar and previous_avatar != user.avatar.name:
        storage = user.avatar.storage
        if storage.exists(previous_avatar):
            storage.delete(previous_avatar)

    record_daily_task_action(
        request.user,
        DailyTask.TaskType.UPDATE_PROFILE,
        related_obj=analyst_profile,
    )
    return JsonResponse({"ok": True, "avatar_url": user.avatar.url, "message": "Аватар обновлён."})


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

    follow, created = AnalystFollow.objects.get_or_create(
        follower=request.user,
        analyst=analyst,
    )
    if created:
        record_daily_task_action(
            request.user,
            DailyTask.TaskType.FOLLOW_CAPPER,
            related_obj=follow,
        )
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

    paid_plans = list(get_active_paid_plans(analyst))
    real_balance = ensure_real_balance(request.user)
    checked_plan_marked = False
    for paid_plan in paid_plans:
        paid_plan.can_afford = real_balance.balance >= paid_plan.price
        paid_plan.is_default_checked = False
        if paid_plan.can_afford and not checked_plan_marked:
            paid_plan.is_default_checked = True
            checked_plan_marked = True
    if paid_plans and not checked_plan_marked:
        paid_plans[0].is_default_checked = True
    legacy_paid_price = profile.paid_predictions_price if not paid_plans else None
    legacy_can_afford = (
        real_balance.balance >= legacy_paid_price
        if legacy_paid_price and legacy_paid_price > 0
        else True
    )
    paid_checkout_can_pay = (
        any(plan.can_afford for plan in paid_plans)
        if paid_plans
        else legacy_can_afford
    )
    if request.method == "GET":
        return render(
            request,
            "cabinet/paid_predictions_checkout.html",
            {
                "expert": analyst,
                "analyst_profile": profile,
                "expert_name": profile.display_name or analyst.get_full_name() or analyst.username,
                "paid_plans": paid_plans,
                "real_balance": real_balance,
                "real_balance_display": format_money(real_balance.balance),
                "legacy_paid_price": legacy_paid_price,
                "legacy_can_afford": legacy_can_afford,
                "paid_checkout_can_pay": paid_checkout_can_pay,
                "next_url": raw_next_url,
            },
        )

    try:
        plan_id = request.POST.get("plan_id") or None
        subscription = subscribe_to_paid_predictions(request.user, analyst, plan_id)
    except (ValueError, ValidationError, InsufficientBalance) as exc:
        messages.error(request, _error_message(exc))
    else:
        messages.success(
            request,
            f"Платная подписка активна до {subscription.expires_at:%d.%m.%Y}.",
        )
    return redirect(raw_next_url)
