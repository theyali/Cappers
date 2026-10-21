from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import transaction
from django.db.models import (
    Case,
    Exists,
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    IntegerField,
    OuterRef,
    Prefetch,
    Q,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.formats import date_format
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.views.decorators.cache import never_cache

from game.models import Country, Prediction, PredictionCoupon, Sport
from game.views import _delete_expired_draft_coupons
from notifications.models import Notification, NotificationSectionState, TelegramAccount
from notifications.services import get_preferences, refresh_section_state
from notifications.telegram_bot import get_bot_token
from notifications.telegram_channels import build_channel_settings_context
from wallets.models import (
    CoinTransaction,
    CopiedBet,
    CopyBettingSubscription,
    RealBalanceTransaction,
)
from front.views import _initials
from wallets.services import ensure_coin_wallet, ensure_real_balance, format_coins, format_money
from wallets.services import InsufficientBalance

from .achievements import build_achievement_overview
from .comments.models import Comment
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
from .models import (
    AnalystFollow,
    AnalystPaidSubscription,
    AnalystProfile,
    CapperArticle,
    DailyTask,
    PresetAvatar,
    User,
)
from .paid_predictions import (
    active_paid_subscriptions,
    active_paid_subscriptions_by_analyst,
    build_paid_subscriptions_preview,
    build_paid_checkout_context,
    get_active_paid_plans,
    profile_paid_subscriptions_enabled,
    paid_subscription_display,
    subscribe_to_paid_predictions,
)
from .referrals import mark_referral_registration
from .services.account_deletion import account_deletion_blockers, delete_user_account
from .services.bonus_center import build_profile_bonus_summary
from .services.capper_articles import (
    build_article_editor_context,
    build_capper_articles_context,
    can_create_capper_article,
    can_edit_capper_article,
    save_capper_article,
    submit_capper_article_for_moderation,
)
from .services.daily_tasks import record_daily_task_action
from .services.verification import grant_verification, verification_state
from .telegram_auth import in_telegram_app
from .vip import annotate_vip_status, attach_vip_status_to_user
from front.prediction_metrics import annotate_author_roi


WALLET_OPERATION_PAGE_SIZE = 20
PROFILE_BEST_COUPONS_LIMIT = 5
PROFILE_SOCIAL_PAGE_SIZE = 8
PROFILE_COMMENTS_PAGE_SIZE = 10
PROFILE_COMMENTS_PREVIEW_LIMIT = 4
FOLLOWING_NEW_PREDICTION_KINDS = (
    Notification.Kind.NEW_PREDICTION,
    Notification.Kind.REQUESTED_MATCH_PREDICTION,
)


def _following_unread_annotations(recipient) -> dict:
    """Unread "new prediction" notices from each followed capper to this reader.

    Subqueries per row: joining every notification the capper ever sent (to all
    readers) and filtering only inside COUNT multiplied the rows badly.
    """
    unread = Notification.objects.filter(
        actor_id=OuterRef("analyst_id"),
        recipient=recipient,
        show_in_app=True,
        is_read=False,
        kind__in=FOLLOWING_NEW_PREDICTION_KINDS,
    ).order_by()
    return {
        "new_predictions_count": Coalesce(
            Subquery(
                unread.values("actor_id").annotate(total=Count("id")).values("total")[:1],
                output_field=IntegerField(),
            ),
            Value(0),
        ),
        "latest_new_prediction_at": Subquery(unread.order_by("-created_at").values("created_at")[:1]),
    }


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


def _compact_count(value) -> str:
    value = int(value or 0)
    if value >= 1_000_000:
        amount = value / 1_000_000
        return f"{amount:.1f} млн".replace(".0", "").replace(".", ",")
    if value >= 1000:
        amount = value / 1000
        return f"{amount:.1f} тыс".replace(".0", "").replace(".", ",")
    return str(value)


def _roi_label(value) -> str:
    try:
        roi = Decimal(str(value or 0))
    except Exception:
        roi = Decimal("0")
    return f"{roi:+.1f}%".replace(".", ",")


def _profile_social_base_queryset(user, kind: str):
    now = timezone.now()
    if kind == "followers":
        if user.role != User.Role.ANALYST:
            return User.objects.none()
        return User.objects.filter(analyst_follows__analyst=user).annotate(
            social_created_at=F("analyst_follows__created_at"),
            social_is_mutual=Exists(
                AnalystFollow.objects.filter(
                    follower=user,
                    analyst_id=OuterRef("pk"),
                )
            ),
            social_is_paid=Exists(
                AnalystPaidSubscription.objects.filter(
                    subscriber_id=OuterRef("pk"),
                    analyst=user,
                    expires_at__gt=now,
                )
            ),
        )

    if kind == "following":
        follows = AnalystFollow.objects.filter(follower=user, analyst_id=OuterRef("pk"))
        paid = active_paid_subscriptions(user).filter(analyst_id=OuterRef("pk"))
        return User.objects.filter(Exists(follows) | Exists(paid)).annotate(
            social_created_at=Coalesce(Subquery(follows.values("created_at")[:1]), Subquery(paid.values("starts_at")[:1])),
            social_is_mutual=Exists(
                AnalystFollow.objects.filter(
                    follower_id=OuterRef("pk"),
                    analyst=user,
                )
            ),
            social_is_paid=Exists(paid),
        )

    if kind == "paid":
        if user.role != User.Role.ANALYST:
            return User.objects.none()
        active_subscription = AnalystPaidSubscription.objects.filter(
            subscriber_id=OuterRef("pk"),
            analyst=user,
            expires_at__gt=now,
        ).order_by("-expires_at", "-id")
        return User.objects.filter(
            Exists(active_subscription),
        ).annotate(
            social_created_at=Subquery(active_subscription.values("starts_at")[:1]),
            social_paid_expires_at=Subquery(active_subscription.values("expires_at")[:1]),
            social_paid_price=Subquery(active_subscription.values("price")[:1]),
            social_is_mutual=Exists(
                AnalystFollow.objects.filter(
                    follower=user,
                    analyst_id=OuterRef("pk"),
                )
            ),
            social_is_paid=Value(True),
        )

    raise Http404("Unknown social list.")


def _profile_social_queryset(user, *, kind: str, filter_key: str, query: str, sort: str):
    if filter_key == "vip":
        outgoing = AnalystFollow.objects.filter(follower=user, analyst_id=OuterRef("pk"))
        incoming = AnalystFollow.objects.filter(follower_id=OuterRef("pk"), analyst=user)
        queryset = User.objects.filter(is_active=True).filter(
            Q(role=User.Role.READER) | Q(role=User.Role.ANALYST, analyst_profile__is_public=True),
        ).annotate(
            social_is_mutual=Exists(outgoing) & Exists(incoming),
            social_is_paid=Exists(active_paid_subscriptions(user).filter(analyst_id=OuterRef("pk"))),
        )
    else:
        queryset = _profile_social_base_queryset(user, kind)
    queryset = queryset.select_related("analyst_profile")
    queryset = annotate_vip_status(queryset, user_outer_ref="pk")
    if filter_key == "vip":
        queryset = queryset.annotate(social_created_at=F("vip_activated_at"))
    queryset = annotate_author_roi(
        queryset,
        author_outer_ref="pk",
        annotation_name="social_roi",
    )
    queryset = queryset.annotate(
        social_followers_count=Coalesce(
            Subquery(
                AnalystFollow.objects.filter(analyst_id=OuterRef("pk"))
                .order_by()
                .values("analyst_id")
                .annotate(total=Count("id"))
                .values("total")[:1],
                output_field=IntegerField(),
            ),
            Value(0),
        ),
        social_predictions_count=Coalesce(
            Subquery(
                PredictionCoupon.objects.filter(
                    author_id=OuterRef("pk"),
                    published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
                )
                .order_by()
                .values("author_id")
                .annotate(total=Count("id"))
                .values("total")[:1],
                output_field=IntegerField(),
            ),
            Value(0),
        ),
    )

    if query:
        queryset = queryset.filter(
            Q(username__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(analyst_profile__display_name__icontains=query)
        )

    if filter_key == "cappers":
        queryset = queryset.filter(role=User.Role.ANALYST)
    elif filter_key == "mutual":
        queryset = queryset.filter(social_is_mutual=True)
    elif filter_key == "vip":
        queryset = queryset.filter(is_vip_active=True)
    elif filter_key == "paid":
        queryset = queryset.filter(social_is_paid=True)

    order_map = {
        "new": ("-social_created_at", "-id"),
        "old": ("social_created_at", "id"),
        "roi": ("-social_roi", "-social_created_at", "-id"),
        "followers": ("-social_followers_count", "-social_created_at", "-id"),
    }
    return queryset.distinct().order_by(*order_map.get(sort, order_map["new"]))


def _profile_social_row(user, person, *, kind: str, following_ids: set[int], paid_subscription=None) -> dict:
    profile = getattr(person, "analyst_profile", None)
    display_name = (
        profile.display_name
        if profile and profile.display_name
        else person.get_full_name() or person.username
    )
    is_analyst = person.role == User.Role.ANALYST
    followers_count = int(getattr(person, "social_followers_count", 0) or 0)
    predictions_count = int(getattr(person, "social_predictions_count", 0) or 0)
    is_paid = bool(getattr(person, "social_is_paid", False))
    is_mutual = bool(getattr(person, "social_is_mutual", False))
    created_at = getattr(person, "social_created_at", None)
    expires_at = getattr(person, "social_paid_expires_at", None)
    meta_parts = []
    if is_analyst:
        meta_parts.append(f"ROI {_roi_label(getattr(person, 'social_roi', 0))}")
        meta_parts.append(f"{_compact_count(predictions_count)} {_ru_plural(predictions_count, 'прогноз', 'прогноза', 'прогнозов')}")
    else:
        meta_parts.append(f"{_compact_count(followers_count)} {_ru_plural(followers_count, 'подписчик', 'подписчика', 'подписчиков')}")
    if is_mutual:
        meta_parts.append("взаимно")
    if is_paid:
        meta_parts.append("платный доступ")

    return {
        "id": person.pk,
        "username": person.username,
        "display_name": display_name,
        "initials": _initials(display_name),
        "avatar_url": person.avatar.url if person.avatar else "",
        "profile_url": (
            reverse("front:expert_profile", kwargs={"username": person.username})
            if is_analyst
            else reverse("cabinet:user_profile", kwargs={"username": person.username})
        ),
        "is_analyst": is_analyst,
        "is_verified": bool(profile and profile.is_verified),
        "is_vip": bool(getattr(person, "is_vip_active", False)),
        "is_mutual": is_mutual,
        "is_paid": is_paid,
        "is_following": person.pk in following_ids,
        "roi_label": _roi_label(getattr(person, "social_roi", 0)),
        "roi_positive": Decimal(str(getattr(person, "social_roi", 0) or 0)) >= 0,
        "followers_label": _compact_count(followers_count),
        "predictions_label": _compact_count(predictions_count),
        "meta": " · ".join(meta_parts),
        "created_label": _relative_time_ru(created_at),
        "paid_expires_label": date_format(
            timezone.localtime(expires_at),
            "j E",
        ) if expires_at else "",
        "paid_price_label": format_money(getattr(person, "social_paid_price", 0) or 0),
        "paid_subscription": paid_subscription_display(paid_subscription) if paid_subscription else None,
        "follow_url": (
            reverse("cabinet:toggle_follow", kwargs={"user_id": person.pk})
            if is_analyst and person.is_active and profile and profile.is_public and person.pk != user.pk
            else ""
        ),
        "follow_label": "Отписаться" if person.pk in following_ids else "Подписаться",
        "follow_aria_label": f"Отписаться от @{person.username}" if person.pk in following_ids else f"Подписаться на @{person.username}",
        "kind": kind,
    }


def _profile_social_context(user, *, kind: str, filter_key="all", query="", sort="new", offset=0, limit=PROFILE_SOCIAL_PAGE_SIZE) -> dict:
    if filter_key not in {"all", "cappers", "mutual", "vip", "paid"}:
        filter_key = "all"
    if sort not in {"new", "old", "roi", "followers"}:
        sort = "new"
    try:
        offset = max(0, int(offset or 0))
    except (TypeError, ValueError):
        offset = 0
    try:
        limit = max(PROFILE_SOCIAL_PAGE_SIZE, min(int(limit), 200))
    except (TypeError, ValueError):
        limit = PROFILE_SOCIAL_PAGE_SIZE

    query = (query or "").strip()
    following_ids = set(user.analyst_follows.values_list("analyst_id", flat=True))
    base = _profile_social_base_queryset(user, kind)
    paid_total = (
        AnalystPaidSubscription.objects.filter(
            analyst=user,
            expires_at__gt=timezone.now(),
        ).count()
        if user.role == User.Role.ANALYST
        else 0
    )
    metrics = {
        "total": base.distinct().count(),
        "week": base.filter(social_created_at__gte=timezone.now() - timedelta(days=7)).distinct().count(),
        "mutual": base.filter(social_is_mutual=True).distinct().count(),
        "paid": paid_total if kind != "following" else base.filter(social_is_paid=True).distinct().count(),
    }
    queryset = _profile_social_queryset(
        user,
        kind=kind,
        filter_key=filter_key,
        query=query,
        sort=sort,
    )
    total = queryset.count()
    users = list(queryset[offset : offset + limit + 1])
    has_more = len(users) > limit
    users = users[:limit]
    paid_by_analyst = (
        active_paid_subscriptions_by_analyst(user, [person.pk for person in users], with_payments=True)
        if kind == "following" or filter_key == "vip" else {}
    )
    rows = [
        _profile_social_row(
            user,
            person,
            kind=kind,
            following_ids=following_ids,
            paid_subscription=paid_by_analyst.get(person.pk),
        )
        for person in users
    ]
    return {
        "profile_social_kind": kind,
        "profile_social_filter": filter_key,
        "profile_social_query": query,
        "profile_social_sort": sort,
        "profile_social_offset": offset,
        "profile_social_next_offset": offset + len(rows),
        "profile_social_remaining": max(0, total - (offset + len(rows))),
        "profile_social_has_more": has_more,
        "profile_social_total": total,
        "profile_social_heading": "VIP-пользователи" if filter_key == "vip" else "Кто следит за вами" if kind == "followers" else "На кого вы подписаны",
        "profile_social_list_title": f"VIP-пользователи · {total}" if filter_key == "vip" else f"Новые за неделю · {metrics['week']}",
        "profile_social_rows": rows,
        "profile_social_metrics": metrics,
        "profile_social_paid_label": "Платные подписки" if kind == "following" else "Платные подписчики",
        "profile_social_paid_metric_label": "Платных подписок" if kind == "following" else "Платных подписчиков",
        "profile_social_paid_preview": build_paid_subscriptions_preview(user) if kind == "following" else [],
        "profile_social_report_url": reverse("cabinet:profile") + ("?tab=wallet" if kind == "following" else "?tab=earnings"),
        "profile_social_report_label": "Баланс" if kind == "following" else "Отчёт",
    }


def _prediction_comment_content_type():
    return ContentType.objects.get_for_model(PredictionCoupon)


def _profile_comments_base_queryset(user, kind: str):
    content_type = _prediction_comment_content_type()
    queryset = (
        Comment.objects.filter(
            content_type=content_type,
            status=Comment.Status.PUBLISHED,
        )
        .filter(Q(parent__isnull=True) | Q(parent__status=Comment.Status.PUBLISHED))
        .select_related("user", "parent", "parent__user", "metrics")
    )
    if kind == "mine":
        return queryset.filter(user=user)
    if kind == "replies":
        return queryset.filter(parent__user=user).exclude(user=user)
    return queryset.filter(
        object_id__in=PredictionCoupon.objects.filter(author=user).values("id")
    ).exclude(user=user)


def _profile_comments_counts(user) -> dict:
    return {
        "received": _profile_comments_base_queryset(user, "received").count(),
        "mine": _profile_comments_base_queryset(user, "mine").count(),
        "replies": _profile_comments_base_queryset(user, "replies").count(),
    }


def _profile_comments_queryset(user, *, kind: str, query: str, sort: str):
    queryset = _profile_comments_base_queryset(user, kind)
    query = (query or "").strip()
    if query:
        queryset = queryset.filter(
            Q(text__icontains=query)
            | Q(user__username__icontains=query)
            | Q(parent__text__icontains=query)
        )
    if sort == "old":
        return queryset.order_by("created_at", "id")
    return queryset.order_by("-created_at", "-id")


def _comment_user_name(user) -> str:
    try:
        profile = user.analyst_profile
    except AnalystProfile.DoesNotExist:
        profile = None
    if profile and profile.display_name:
        return profile.display_name
    return user.get_full_name() or user.username


def _profile_comment_target_context(comment, coupon_map, first_position_map) -> dict:
    coupon = coupon_map.get(comment.object_id)
    position = first_position_map.get(comment.object_id)
    if not coupon:
        return {
            "title": "Прогноз",
            "meta": "",
            "url": "#",
        }

    title = coupon.headline or "Прогноз"
    meta = ""
    if position:
        match = position.match
        title = (
            f"{match.home_team_name or 'Хозяева'} — {match.away_team_name or 'Гости'}"
        )
        coefficient = position.coefficient.quantize(Decimal("0.01")) if position.coefficient else ""
        meta = f"{position.selection} {coefficient}".strip()

    return {
        "title": title,
        "meta": meta,
        "url": f"{reverse('front:prediction_detail', kwargs={'prediction_id': coupon.pk})}#comment-{comment.pk}",
    }


def _profile_comments_rows(comments) -> list[dict]:
    coupon_ids = {comment.object_id for comment in comments}
    coupons = (
        PredictionCoupon.objects.filter(pk__in=coupon_ids)
        .select_related("author", "author__analyst_profile")
    )
    coupon_map = {coupon.pk: coupon for coupon in coupons}
    first_position_map = {}
    for position in (
        Prediction.objects.filter(coupon_id__in=coupon_ids)
        .select_related("match")
        .order_by("coupon_id", "id")
    ):
        first_position_map.setdefault(position.coupon_id, position)

    reply_parent_ids = [
        comment.pk
        for comment in comments
        if comment.parent_id is None
    ]
    my_replies = {}
    if reply_parent_ids:
        for reply in (
            Comment.objects.filter(
                parent_id__in=reply_parent_ids,
                status=Comment.Status.PUBLISHED,
            )
            .select_related("user")
            .order_by("created_at", "id")
        ):
            my_replies.setdefault(reply.parent_id, reply)

    rows = []
    for comment in comments:
        author = comment.user
        target = _profile_comment_target_context(comment, coupon_map, first_position_map)
        parent = comment.parent
        parent_id = comment.parent_id
        my_reply = my_replies.get(comment.pk)
        rows.append(
            {
                "id": comment.pk,
                "comment": comment,
                "author": author,
                "author_name": _comment_user_name(author),
                "author_url": reverse("cabinet:user_profile", kwargs={"username": author.username}),
                "author_avatar_url": _field_url(author.avatar),
                "created_label": _relative_time_ru(comment.created_at),
                "target": target,
                "parent_text": parent.text if parent_id and parent else "",
                "parent_author": _comment_user_name(parent.user) if parent_id and parent else "",
                "my_reply": my_reply,
                "my_reply_label": _relative_time_ru(my_reply.created_at) if my_reply else "",
                "is_unanswered": comment.parent_id is None and my_reply is None,
                "comment_url": target["url"],
            }
        )
    return rows


def _profile_comments_context(
    user,
    *,
    kind: str = "received",
    query: str = "",
    sort: str = "new",
    offset: int = 0,
    limit: int = PROFILE_COMMENTS_PAGE_SIZE,
) -> dict:
    if kind not in {"received", "mine", "replies"}:
        kind = "received"
    if sort not in {"new", "old"}:
        sort = "new"
    offset = max(0, int(offset or 0))
    limit = max(1, int(limit or PROFILE_COMMENTS_PAGE_SIZE))

    counts = _profile_comments_counts(user)
    queryset = _profile_comments_queryset(user, kind=kind, query=query, sort=sort)
    total = queryset.count()
    comments = list(queryset[offset : offset + limit + 1])
    visible = comments[:limit]
    rows = _profile_comments_rows(visible)

    return {
        "profile_comments_kind": kind,
        "profile_comments_query": query,
        "profile_comments_sort": sort,
        "profile_comments_counts": counts,
        "profile_comments_rows": rows,
        "profile_comments_total": total,
        "profile_comments_next_offset": offset + len(rows),
        "profile_comments_has_more": len(comments) > limit,
        "profile_comments_remaining": max(0, total - (offset + len(rows))),
    }


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

    return render(request, "cabinet/capper_article_form.html", build_article_editor_context(request.user, form, article))


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

    return render(request, "cabinet/capper_article_form.html", build_article_editor_context(request.user, form, article))


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


def _is_ajax(request) -> bool:
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


def _profile_name(user, analyst_profile) -> str:
    if analyst_profile is not None and analyst_profile.display_name:
        return analyst_profile.display_name
    return user.get_full_name() or user.username


def _verification_html(user, analyst_profile) -> str:
    if analyst_profile is None:
        return ""
    return render_to_string(
        "cabinet/includes/_profile_verification.html",
        {"verification": verification_state(user, analyst_profile)},
    )


def _settings_errors_response(*forms) -> JsonResponse:
    """Form errors for the settings page, keyed by input name."""
    field_errors = {}
    other_errors = []
    for form in forms:
        if form is None:
            continue
        for field, errors in form.errors.items():
            if field == NON_FIELD_ERRORS:
                other_errors.extend(errors)
            else:
                field_errors[form.add_prefix(field)] = list(errors)
    return JsonResponse(
        {
            "ok": False,
            "message": "Проверьте поля с ошибками.",
            "errors": field_errors,
            "non_field_errors": other_errors,
        },
        status=400,
    )


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


def _coupon_positions_queryset():
    return (
        Prediction.objects.select_related("match", "match__sport", "match__league")
        .order_by("id")
    )


def _combined_coefficient_expression():
    return Case(
        When(
            total_stake__gt=0,
            then=ExpressionWrapper(
                F("possible_payout") / F("total_stake"),
                output_field=DecimalField(max_digits=12, decimal_places=4),
            ),
        ),
        default=Value(Decimal("0")),
        output_field=DecimalField(max_digits=12, decimal_places=4),
    )


def _profile_coupons_queryset(user, *, purchased_coupon_ids=None):
    if purchased_coupon_ids is not None:
        coupons = PredictionCoupon.objects.filter(pk__in=purchased_coupon_ids)
    else:
        coupons = PredictionCoupon.objects.filter(author=user)
    return (
        coupons
        .exclude(published_status=PredictionCoupon.PublishedStatus.DRAFT)
        .select_related("metrics")
        .annotate(
            predictions_count=Count("predictions", distinct=True),
            unique_opens_count=Coalesce(F("metrics__unique_opens_count"), Value(0), output_field=IntegerField()),
            likes_count=Coalesce(
                F("metrics__likes_count"),
                Value(0),
                output_field=IntegerField(),
            ),
            favorites_count=Coalesce(
                F("metrics__favorites_count"),
                Value(0),
                output_field=IntegerField(),
            ),
            comments_count=Coalesce(
                F("metrics__comments_count"),
                Value(0),
                output_field=IntegerField(),
            ),
            combined_coefficient=_combined_coefficient_expression(),
        )
        .prefetch_related(
            Prefetch(
                "predictions",
                queryset=_coupon_positions_queryset(),
                to_attr="profile_positions",
            )
        )
    )


def _sort_profile_coupons(queryset, sort_key: str, direction: str):
    sort_fields = {
        "date": "created_at",
        "stake": "total_stake",
        "payout": "possible_payout",
        "likes": "likes_count",
        "favorites": "favorites_count",
    }
    field = sort_fields.get(sort_key, "created_at")
    prefix = "" if direction == "asc" else "-"
    return queryset.order_by(f"{prefix}{field}", f"{prefix}id")


def _coupon_state_label(state_status: str) -> str:
    if state_status == PredictionCoupon.StateStatus.WIN:
        return "Выигрыш"
    if state_status == PredictionCoupon.StateStatus.LOSE:
        return "Проигрыш"
    if state_status == PredictionCoupon.StateStatus.REFUND:
        return "Возврат"
    return "В игре"


def _field_url(field) -> str:
    if not field:
        return ""
    try:
        return field.url
    except ValueError:
        return ""


def _coupon_cover_urls(coupon: PredictionCoupon) -> tuple[str, str]:
    if coupon.custom_cover_image:
        cover_url = _field_url(coupon.custom_cover_image)
        return cover_url, cover_url

    cover = coupon.cover_image if coupon.cover_image_id else coupon.assign_cover_image()
    cover_url = _field_url(cover.image if cover else None)
    mobile_cover_url = _field_url(cover.mobile_image if cover else None) or cover_url
    return cover_url, mobile_cover_url


def _mobile_coupon_cards(coupons, author) -> list[dict]:
    cards = []
    try:
        profile = author.analyst_profile
    except AnalystProfile.DoesNotExist:
        profile = None

    expert_name = (
        profile.display_name
        if profile and profile.display_name
        else author.get_full_name() or author.username
    )
    for coupon in coupons:
        positions = list(getattr(coupon, "profile_positions", []) or [])
        if not positions:
            continue

        item = positions[0]
        match = item.match
        count = len(positions)
        starts_at = "Время не указано"
        starts_short = ""
        if match.starts_at:
            local_starts_at = timezone.localtime(match.starts_at)
            starts_at = local_starts_at.strftime("%d.%m · %H:%M")
            starts_short = f"{date_format(local_starts_at, 'j b')} · {local_starts_at:%H:%M}"

        coefficient = item.coefficient
        pick_short = item.selection
        market = item.market
        if count > 1:
            pick_short = "Экспресс"
            market = f"Экспресс · {count} игр"
            coefficient = (
                coupon.possible_payout / coupon.total_stake
                if coupon.total_stake
                else Decimal("0")
            )
        cover_url, mobile_cover_url = _coupon_cover_urls(coupon)

        cards.append(
            {
                "id": coupon.id,
                "created_at": coupon.created_at,
                "total_stake": coupon.total_stake,
                "possible_payout": coupon.possible_payout,
                "sport": (
                    match.sport.name_ru
                    if match.sport and match.sport.name_ru
                    else "Спорт"
                ),
                "league": match.league_name or "Лига",
                "home_name": match.home_team_name or "Хозяева",
                "away_name": match.away_team_name or "Гости",
                "pick_short": pick_short,
                "market": market,
                "coefficient": coefficient.quantize(Decimal("0.01")),
                "positions_count": count,
                "starts_at": starts_at,
                "starts_short": starts_short,
                "cover_url": cover_url,
                "mobile_cover_url": mobile_cover_url,
                "expert": expert_name,
                "expert_initials": _initials(expert_name),
                "expert_avatar_url": author.avatar.url if author.avatar else "",
                "expert_verified": bool(profile and profile.is_verified),
                "expert_trust_index": profile.trust_index if profile else Decimal("0.0"),
            }
        )
    return cards


def _expert_mobile_coupon_cards(coupons) -> list[dict]:
    cards = []
    for coupon in coupons:
        positions = list(getattr(coupon, "profile_positions", []) or [])
        if not positions:
            continue

        item = positions[0]
        match = item.match
        count = len(positions)
        is_express = coupon.coupon_type == PredictionCoupon.CouponType.EXPRESS
        coefficient = getattr(coupon, "combined_coefficient", None)
        if coefficient is None:
            coefficient = (
                coupon.possible_payout / coupon.total_stake
                if coupon.total_stake
                else Decimal("0")
            )
        subtitle = item.selection
        if count > 1:
            subtitle = f"Экспресс · {count} игр · {item.selection}"
        elif item.market:
            subtitle = f"{item.market} · {item.selection}"

        cards.append(
            {
                "id": coupon.id,
                "created_at": coupon.created_at,
                "total_stake": coupon.total_stake,
                "possible_payout": coupon.possible_payout,
                "unique_opens_count": coupon.unique_opens_count,
                "likes_count": coupon.likes_count,
                "comments_count": coupon.comments_count,
                "favorites_count": coupon.favorites_count,
                "positions_count": count,
                "is_express": is_express,
                "state_status": coupon.state_status,
                "state_label": _coupon_state_label(coupon.state_status),
                "sport_code": match.sport.code if match.sport else "",
                "sport_name": (
                    match.sport.name_ru
                    if match.sport and match.sport.name_ru
                    else "Спорт"
                ),
                "league_name": match.league_name or "",
                "starts_at": match.starts_at,
                "score": match.score or "",
                "title": f"{match.home_team_name or 'Хозяева'} — {match.away_team_name or 'Гости'}",
                "subtitle": subtitle,
                "coefficient": Decimal(coefficient or 0).quantize(Decimal("0.01")),
            }
        )
    return cards



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
            if _is_ajax(request):
                return JsonResponse(
                    {
                        "ok": True,
                        "message": "Быстрый доступ обновлён.",
                        "quick_access_html": render_to_string(
                            "front/includes/_mobile_quick_access_grid.html",
                            request=request,
                        ),
                    }
                )
            messages.success(request, "Быстрый доступ обновлён.")
            return redirect(f"{reverse('cabinet:profile')}?tab=settings")
        if _is_ajax(request):
            return _settings_errors_response(mobile_quick_access_form)
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

        if paid_plans_are_valid and paid_plan_form is not None and analyst_is_valid:
            paid_plans_are_valid = paid_plan_form.validate_sales_options(
                paid_enabled=paid_predictions_enabled,
                single_enabled=analyst_form.cleaned_data.get("single_coupon_sales_enabled"),
                single_price=analyst_form.cleaned_data.get("single_coupon_price"),
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
            if _is_ajax(request):
                return JsonResponse(
                    {
                        "ok": True,
                        "message": "Профиль обновлён.",
                        "profile_name": _profile_name(request.user, analyst_profile),
                        "profile_completion": _profile_completion(request.user, analyst_profile),
                        "verification_html": _verification_html(request.user, analyst_profile),
                    }
                )
            messages.success(request, "Профиль обновлён.")
            return redirect(f"{reverse('cabinet:profile')}?tab=settings")
        if _is_ajax(request):
            return _settings_errors_response(
                user_form,
                analyst_form,
                focus_form,
                paid_plan_form if paid_predictions_enabled else None,
            )
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
            **_following_unread_annotations(request.user),
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

    earnings_context = {}
    active_paid_subscriber_ids = set()
    if request.user.role == User.Role.ANALYST:
        earnings_context = build_earnings_context(request.user)
        active_paid_subscriber_ids = {
            subscription.subscriber_id
            for subscription in earnings_context["active_paid_subscriptions"]
        }
    active_paid_subscribers = len(active_paid_subscriber_ids)
    followers_social_context = (
        _profile_social_context(request.user, kind="followers")
        if request.user.role == User.Role.ANALYST
        else {}
    )
    following_social_context = _profile_social_context(request.user, kind="following")

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

    profile_best_mobile_coupons = []
    profile_best_expresses = []
    profile_coupon_stats = {"total": 0, "wins": 0, "losses": 0, "win_rate": 0}
    coupons_count = 0
    predictions_count = 0
    if request.user.role == User.Role.ANALYST:
        _delete_expired_draft_coupons(request.user)
        base_coupons = _profile_coupons_queryset(request.user)
        counts = base_coupons.aggregate(
            total=Count("pk", distinct=True),
            wins=Count("pk", filter=Q(state_status=PredictionCoupon.StateStatus.WIN), distinct=True),
            losses=Count("pk", filter=Q(state_status=PredictionCoupon.StateStatus.LOSE), distinct=True),
        )
        coupons_count = counts["total"]
        predictions_count = coupons_count
        profile_coupon_stats = {
            **counts,
            "win_rate": round(counts["wins"] * 100 / coupons_count) if coupons_count else 0,
        }
        winning_expresses = base_coupons.filter(
            state_status=PredictionCoupon.StateStatus.WIN,
            predictions_count__gt=1,
        ).order_by("-combined_coefficient", "-created_at", "-id")[:3]
        profile_best_expresses = _expert_mobile_coupon_cards(winning_expresses)
        best_coupons = list(
            base_coupons.filter(state_status=PredictionCoupon.StateStatus.WIN)
            .order_by("-combined_coefficient", "-created_at", "-id")[
                :PROFILE_BEST_COUPONS_LIMIT
            ]
        )
        profile_best_mobile_coupons = _mobile_coupon_cards(best_coupons, request.user)


    achievement_overview = build_achievement_overview(
        request.user,
        followers_count=followers_count,
        is_verified=bool(analyst_profile and analyst_profile.is_verified),
    )

    verification = (
        verification_state(request.user, analyst_profile)
        if analyst_profile is not None
        else None
    )
    profile_completion = _profile_completion(request.user, analyst_profile)
    profile_bonus_summary = (
        build_profile_bonus_summary(request.user)
        if active_tab == "profile"
        else None
    )
    profile_comments_preview = (
        _profile_comments_context(
            request.user,
            kind="received",
            limit=PROFILE_COMMENTS_PREVIEW_LIMIT,
        )
        if active_tab == "profile"
        else None
    )

    preset_avatars = PresetAvatar.objects.filter(is_active=True).order_by("sort_order", "pk")
    preset_avatar_counts = {
        "all": preset_avatars.count(),
        "male": preset_avatars.filter(gender=PresetAvatar.Gender.MALE).count(),
        "female": preset_avatars.filter(gender=PresetAvatar.Gender.FEMALE).count(),
    }

    context = {
        "analyst_profile": analyst_profile,
        "user_form": user_form,
        "analyst_form": analyst_form,
        "focus_form": focus_form,
        "paid_plan_form": paid_plan_form,
        "mobile_quick_access_form": mobile_quick_access_form,
        "active_tab": active_tab,
        "preset_avatars": preset_avatars[:60],
        "preset_avatar_counts": preset_avatar_counts,
        "followers_count": followers_count,
        "following_count": following_count,
        "followers": followers,
        "following": following,
        "following_new_analysts_count": following_new_analysts_count,
        "following_ids": following_ids,
        "active_paid_subscribers": active_paid_subscribers,
        "active_paid_subscriber_ids": active_paid_subscriber_ids,
        "followers_social": followers_social_context,
        "following_social": following_social_context,
        "profile_best_mobile_coupons": profile_best_mobile_coupons,
        "profile_best_expresses": profile_best_expresses,
        "profile_coupon_stats": profile_coupon_stats,
        "coupons_count": coupons_count,
        "predictions_count": predictions_count,
        "achievement_overview": achievement_overview,
        "profile_completion": profile_completion,
        "verification": verification,
        "profile_bonus_summary": profile_bonus_summary,
        "profile_comments_preview": profile_comments_preview,
        "notification_preferences": notification_preferences,
        "telegram_account": telegram_account,
        "telegram_bot_configured": bool(get_bot_token()),
        "coin_wallet": coin_wallet,
        "coin_balance_display": format_coins(coin_wallet.balance),
        "real_balance": real_balance,
        "real_balance_display": format_money(real_balance.balance) if real_balance else "",
        "real_pending_withdrawal_display": format_money(real_balance.pending_withdrawal) if real_balance else "",
        "real_held_display": format_money(real_balance.held) if real_balance and real_balance.held else "",
        "delete_account_blockers": account_deletion_blockers(request.user),
        "coin_transactions": coin_transactions,
        "real_transactions": real_transactions,
        "page_class": "profile",
    }
    if request.user.role == User.Role.ANALYST:
        from .services.profile_coupon_feed import build_coupon_feed_context
        context.update(build_coupon_feed_context(request.user, request.GET, offset=0))
        context.update(build_channel_settings_context(request.user))
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
    from cabinet.services.copybetting import build_copybetting_context
    context.update(build_copybetting_context(request.user, request.GET))
    if request.user.role == User.Role.ANALYST:
        context.update(build_dashboard_context(request.user))
        context.update(earnings_context)

    return render(request, "cabinet/profile.html", context)


@login_required
@require_GET
def profile_comments(request):
    context = _profile_comments_context(
        request.user,
        kind=request.GET.get("kind", "received"),
        query=request.GET.get("q", ""),
        sort=request.GET.get("sort", "new"),
        offset=request.GET.get("offset", 0),
    )
    context.update(
        {
            "active_tab": "comments",
            "page_class": "profile profile-comments-page",
        }
    )
    if _is_ajax(request):
        return JsonResponse(
            {
                "html": render_to_string(
                    "cabinet/includes/_profile_comments_rows.html",
                    context,
                    request=request,
                ),
                "total": context["profile_comments_total"],
                "counts": context["profile_comments_counts"],
                "has_more": context["profile_comments_has_more"],
                "next_offset": context["profile_comments_next_offset"],
                "remaining": context["profile_comments_remaining"],
            }
        )
    return render(request, "cabinet/profile_comments.html", context)


@login_required
@require_GET
def profile_mobile_coupons(request):
    if request.user.role != User.Role.ANALYST:
        return JsonResponse({"ok": False, "message": "Недоступно."}, status=403)

    from .services.profile_coupon_feed import build_coupon_feed_context, build_coupon_feed_payload

    return JsonResponse(build_coupon_feed_payload(request, build_coupon_feed_context(request.user, request.GET)))


@login_required
@require_GET
def profile_social(request):
    kind = request.GET.get("kind", "following")
    if kind not in {"followers", "following", "paid"}:
        return JsonResponse({"ok": False, "message": "Неизвестный список."}, status=400)
    if kind in {"followers", "paid"} and request.user.role != User.Role.ANALYST:
        return JsonResponse({"ok": False, "message": "Недоступно."}, status=403)

    context = _profile_social_context(
        request.user,
        kind=kind,
        filter_key=request.GET.get("filter", "all"),
        query=request.GET.get("q", ""),
        sort=request.GET.get("sort", "new"),
        offset=request.GET.get("offset", 0),
        limit=request.GET.get("limit", PROFILE_SOCIAL_PAGE_SIZE),
    )
    html = render_to_string(
        "cabinet/includes/_profile_social_rows.html",
        context,
        request=request,
    )
    return JsonResponse(
        {
            "ok": True,
            "html": html,
            "total": context["profile_social_total"],
            "heading": context["profile_social_heading"],
            "list_title": context["profile_social_list_title"],
            "metrics": context["profile_social_metrics"],
            "has_more": context["profile_social_has_more"],
            "next_offset": context["profile_social_next_offset"],
            "paid_preview_html": render_to_string(
                "cabinet/includes/_profile_paid_subscriptions_preview.html", context, request=request,
            ) if kind == "following" else "",
        }
    )


@login_required
@require_POST
def delete_account(request):
    if request.POST.get("confirmation") != "delete-account":
        messages.error(request, "Подтвердите удаление аккаунта.")
        return redirect(f"{reverse('cabinet:profile')}?tab=settings")

    try:
        delete_user_account(request.user)
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return redirect(f"{reverse('cabinet:profile')}?tab=settings")

    logout(request)
    messages.success(request, "Аккаунт удалён, личные данные стёрты.")
    return redirect("front:index")


@login_required
@require_POST
def request_verification(request):
    analyst_profile = _get_analyst_profile(request.user)
    if analyst_profile is None:
        ok, message = False, "Галочка доступна только капперам."
    else:
        ok, message = grant_verification(request.user, analyst_profile)
        analyst_profile.refresh_from_db(fields=["is_verified", "verification_requested_at"])

    if _is_ajax(request):
        payload = {"ok": ok, "message": message}
        if analyst_profile is not None:
            payload["verification_html"] = _verification_html(request.user, analyst_profile)
            if analyst_profile.is_verified:
                payload["badge_html"] = render_to_string("cabinet/includes/_capper_verified_badge.html")
        return JsonResponse(payload, status=200 if ok else 400)

    if ok:
        messages.success(request, message)
    else:
        messages.error(request, message)
    return redirect(f"{reverse('cabinet:profile')}?tab=settings")


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
            predictions_count=Coalesce(
                Subquery(
                    PredictionCoupon.objects.filter(
                        author_id=OuterRef("analyst_id"),
                        published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
                        audience=PredictionCoupon.Audience.FREE,
                    )
                    .order_by()
                    .values("author_id")
                    .annotate(total=Count("id"))
                    .values("total")[:1],
                    output_field=IntegerField(),
                ),
                Value(0),
            ),
            followers_count=Coalesce(
                Subquery(
                    AnalystFollow.objects.filter(analyst_id=OuterRef("analyst_id"))
                    .order_by()
                    .values("analyst_id")
                    .annotate(total=Count("id"))
                    .values("total")[:1],
                    output_field=IntegerField(),
                ),
                Value(0),
            ),
            **_following_unread_annotations(request.user),
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
@require_http_methods(["GET", "POST"])
@never_cache
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

    if not profile or not profile_paid_subscriptions_enabled(analyst):
        messages.error(request, "Этот эксперт не публикует платные прогнозы.")
        return redirect(expert_url)

    wants_json = request.headers.get("x-requested-with") == "XMLHttpRequest"
    if request.method == "GET" and not wants_json:
        if urlsplit(raw_next_url).path == request.path:
            raw_next_url = expert_url
        target = urlsplit(raw_next_url)
        query = [(key, value) for key, value in parse_qsl(target.query) if key != "paid_subscribe"]
        query.append(("paid_subscribe", str(analyst.pk)))
        if request.GET.get("plan_id", "").isdigit():
            query = [(key, value) for key, value in query if key != "paid_plan"]
            query.append(("paid_plan", request.GET["plan_id"]))
        return redirect(urlunsplit(target._replace(query=urlencode(query))))

    if request.method == "GET":
        return render(
            request,
            "cabinet/includes/_subscription_checkout.html",
            {
                "expert": analyst,
                "analyst_profile": profile,
                "expert_name": profile.display_name or analyst.get_full_name() or analyst.username,
                "next_url": raw_next_url,
                **build_paid_checkout_context(
                    request.user,
                    profile,
                    list(get_active_paid_plans(analyst)),
                    in_telegram_app=in_telegram_app(request),
                    selected_plan_id=request.GET.get("plan_id"),
                ),
            },
        )

    if request.user.role != User.Role.ANALYST:
        if wants_json:
            return JsonResponse({"ok": False, "message": "Выберите способ прямой оплаты."}, status=403)
        messages.error(request, "Выберите способ прямой оплаты.")
        return redirect(request.path)
    try:
        plan_id = request.POST.get("plan_id") or None
        subscription = subscribe_to_paid_predictions(request.user, analyst, plan_id)
    except (ValueError, ValidationError, InsufficientBalance) as exc:
        if wants_json:
            return JsonResponse({"ok": False, "message": _error_message(exc)}, status=400)
        messages.error(request, _error_message(exc))
    else:
        messages.success(request, f"Платная подписка активна до {subscription.expires_at:%d.%m.%Y}.")
        if wants_json:
            return JsonResponse({"ok": True, "return_url": raw_next_url})
    return redirect(raw_next_url)
