from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Count, Exists, OuterRef, Q
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie

from cabinet.models import AnalystFollow, AnalystPaidSubscription, AnalystProfile, DailyTask, User
from cabinet.services.daily_tasks import record_daily_task_action
from cabinet.vip import annotate_vip_status, attach_vip_status_to_user, plural_ru
from game.models import Match, PredictionCoupon, Sport
from notifications.models import Notification

from .prediction_metrics import annotate_author_roi
from .prediction_catalog_views import (
    PREDICTION_TYPE_CLASSIC,
    PREDICTION_TYPE_PAID,
    PREDICTION_TYPE_VIP,
    build_prediction_type_context,
    build_vip_prediction_rail_context,
    _attach_paid_catalog_access,
)
from .prediction_head import apply_prediction_status, build_prediction_head, prediction_sport_counts
from .prediction_views import (
    PREDICTIONS_PAGE_SIZE,
    SORT_OPTIONS,
    _decorate_predictions,
    _sort_prediction_queryset,
    _published_queryset,
    _status_tabs,
    prediction_filter_collapsed,
)
from .sport_tabs import (
    build_mobile_prediction_filter_tabs,
    build_mobile_prediction_match_scope_tabs,
    build_sport_filter_tabs,
)
from .views import PREDICTION_STATUS_FILTERS


FEED_SORT_OPTIONS = tuple(option for option in SORT_OPTIONS if option[0] != "roi")
VIP_STORIES_LIMIT = 30
FEED_META_CACHE_TTL = 60


def _feed_cache_key(user_id: int, namespace: str, *parts) -> str:
    import hashlib

    signature = hashlib.sha1(repr(parts).encode("utf-8")).hexdigest()[:20]
    return f"front:feed:{namespace}:v5:{user_id}:{signature}"


def _feed_url(request, params) -> str:
    query = params.urlencode()
    return f"{request.path}?{query}" if query else request.path


def _vip_story_payloads(user, limit: int = VIP_STORIES_LIMIT) -> tuple[list[dict], int]:
    live_coupons = PredictionCoupon.objects.filter(
        author_id=OuterRef("user_id"),
        published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        state_status=PredictionCoupon.StateStatus.PENDING,
        predictions__match__sync_scope=Match.SyncScope.LIVE,
    )
    queryset = annotate_vip_status(
        AnalystProfile.objects.filter(
            is_public=True,
            user__role=User.Role.ANALYST,
        ).select_related("user"),
        user_outer_ref="user_id",
        activated_annotation_name="vip_subscription_activated_at",
    ).filter(is_vip_active=True)
    queryset = annotate_author_roi(
        queryset,
        author_outer_ref="user_id",
    ).annotate(has_live_prediction=Exists(live_coupons))

    total_count = queryset.count()
    profiles = list(queryset.order_by("-vip_subscription_activated_at", "-user_id")[:limit])
    author_ids = [profile.user_id for profile in profiles]
    unread_by_author = {
        row["actor_id"]: row["total"]
        for row in Notification.objects.filter(
            recipient=user,
            actor_id__in=author_ids,
            kind__in=(
                Notification.Kind.NEW_PREDICTION,
                Notification.Kind.REQUESTED_MATCH_PREDICTION,
            ),
            show_in_app=True,
            is_read=False,
        ).values("actor_id").annotate(total=Count("id"))
    } if author_ids else {}

    stories = []
    for profile in profiles:
        author = profile.user
        name = profile.display_name or author.get_full_name() or author.username
        parts = name.split()
        roi = profile.author_roi
        stories.append(
            {
                "id": author.pk,
                "name": name,
                "short_name": parts[0] if parts else author.username,
                "initials": "".join(part[0] for part in parts[:2]).upper() or "К",
                "avatar_url": author.avatar.url if author.avatar else "",
                "profile_url": reverse(
                    "front:expert_profile",
                    kwargs={"username": author.username},
                ),
                "roi_label": f"{roi:+.1f}%".replace(".", ","),
                "roi_positive": roi >= 0,
                "is_verified": profile.is_verified,
                "is_live": profile.has_live_prediction,
                "unread_count": unread_by_author.get(author.pk, 0),
            }
        )
    return stories, total_count


def _sport_from_filter(value: str) -> Sport | None:
    if not value:
        return None
    queryset = Sport.objects.all()
    if value.isdigit():
        return queryset.filter(pk=int(value)).first()
    return queryset.filter(code__iexact=value).first()


def _feed_meta_queryset(*, audience: str, author_ids=None, favorites_user=None) -> object:
    """Cheap coupon queryset for tabs/counts without card annotations or ROI subqueries."""
    queryset = PredictionCoupon.objects.filter(
        published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        audience=audience,
    )
    if author_ids is not None:
        queryset = queryset.filter(author_id__in=author_ids)
    if favorites_user is not None:
        queryset = queryset.filter(favorites__user=favorites_user).distinct()
    return queryset

def _apply_feed_filters(
    queryset,
    *,
    selected_capper,
    selected_sport,
    only_live,
    only_today,
    match_scope="all",
    express_only=False,
):
    if selected_capper:
        queryset = queryset.filter(author__username=selected_capper)
    if express_only:
        queryset = queryset.filter(coupon_type=PredictionCoupon.CouponType.EXPRESS)
    if selected_sport:
        queryset = queryset.filter(predictions__match__sport=selected_sport)
    if match_scope != "all":
        queryset = queryset.filter(predictions__match__sync_scope=match_scope)
    elif only_live:
        queryset = queryset.filter(predictions__match__sync_scope="live")
    if only_today:
        queryset = queryset.filter(predictions__match__starts_at__date=timezone.localdate())
    return queryset.distinct()


def _feed_counts(queryset, *, cache_key: str) -> dict:
    counts = cache.get(cache_key)
    if counts is not None:
        return counts

    counts = queryset.aggregate(
        total=Count("id", distinct=True),
        pending=Count(
            "id",
            filter=Q(state_status=PredictionCoupon.StateStatus.PENDING),
            distinct=True,
        ),
        win=Count(
            "id",
            filter=Q(state_status=PredictionCoupon.StateStatus.WIN),
            distinct=True,
        ),
        lose=Count(
            "id",
            filter=Q(state_status=PredictionCoupon.StateStatus.LOSE),
            distinct=True,
        ),
        refund=Count(
            "id",
            filter=Q(state_status=PredictionCoupon.StateStatus.REFUND),
            distinct=True,
        ),
    )
    cache.set(cache_key, counts, FEED_META_CACHE_TTL)
    return counts


def _feed_status_count(counts: dict, active_status: str) -> int:
    key = "total" if active_status == "all" else active_status
    return counts.get(key, 0) or 0


@login_required
@ensure_csrf_cookie
def following_feed(request):
    record_daily_task_action(request.user, DailyTask.TaskType.OPEN_FEED)
    prediction_type_context = build_prediction_type_context(request)
    prediction_format = prediction_type_context["prediction_format"]
    active_prediction_type = prediction_type_context["active_prediction_type"]
    is_paid_predictions_tab = active_prediction_type == PREDICTION_TYPE_PAID
    is_vip_predictions_tab = active_prediction_type == PREDICTION_TYPE_VIP

    active_status = request.GET.get("status", "all")
    valid_statuses = {key for key, _ in PREDICTION_STATUS_FILTERS}
    if active_status not in valid_statuses:
        active_status = "all"

    active_sort = request.GET.get("sort", "new")
    valid_sorts = {key for key, _ in FEED_SORT_OPTIONS}
    if active_sort not in valid_sorts:
        active_sort = "new"

    following = list(
        annotate_vip_status(
            AnalystFollow.objects.filter(follower=request.user).select_related(
                "analyst",
                "analyst__analyst_profile",
            ),
            user_outer_ref="analyst_id",
        )
        .order_by("-created_at")
    )
    for follow in following:
        attach_vip_status_to_user(follow.analyst, follow)
    following_ids = {follow.analyst_id for follow in following}
    followed_usernames = {follow.analyst.username for follow in following}
    paid_subscriptions = list(
        AnalystPaidSubscription.objects.filter(
            subscriber=request.user,
            expires_at__gt=timezone.now(),
        )
        .select_related("analyst", "analyst__analyst_profile")
        .order_by("-expires_at", "-id")
    )
    paid_analyst_ids = {subscription.analyst_id for subscription in paid_subscriptions}
    paid_source_ids = following_ids | paid_analyst_ids
    paid_usernames = {subscription.analyst.username for subscription in paid_subscriptions}
    vip_stories, vip_stories_count = _vip_story_payloads(request.user)

    selected_capper = request.GET.get("capper", "").strip()
    if selected_capper and selected_capper not in followed_usernames | paid_usernames:
        selected_capper = ""

    selected_sport = _sport_from_filter(request.GET.get("sport", "").strip())
    active_express = request.GET.get("express") == "1"
    favorites_only = request.GET.get("favorites") == "1"
    if active_express:
        selected_sport = None
    only_live = request.GET.get("live") == "1"
    only_today = request.GET.get("today") == "1"
    active_match_scope = request.GET.get("match_scope", "all")
    if active_match_scope not in {"all", "live", "prematch", "finished"}:
        active_match_scope = "all"

    feed_source_signature = (
        tuple(sorted(following_ids)),
        tuple(sorted(paid_analyst_ids)),
        selected_capper,
        only_live,
        only_today,
        active_match_scope,
        active_prediction_type,
        favorites_only,
    )

    # Metadata (tabs/counts) intentionally uses lightweight querysets. The full
    # card queryset contains ROI annotations/selects/prefetches and is much more
    # expensive to aggregate over.
    free_meta_queryset = _apply_feed_filters(
        _feed_meta_queryset(
            audience=PredictionCoupon.Audience.FREE,
            author_ids=None if favorites_only else following_ids,
            favorites_user=request.user if favorites_only else None,
        ),
        selected_capper=selected_capper,
        selected_sport=None,
        only_live=only_live,
        only_today=only_today,
        match_scope=active_match_scope,
    )
    if active_prediction_type != PREDICTION_TYPE_CLASSIC:
        free_meta_queryset = free_meta_queryset.filter(prediction_format=prediction_format)
    if is_vip_predictions_tab:
        free_meta_queryset = annotate_vip_status(free_meta_queryset, user_outer_ref="author_id")
        free_meta_queryset = free_meta_queryset.filter(is_vip_active=True)
    paid_meta_queryset = _apply_feed_filters(
        _feed_meta_queryset(
            audience=PredictionCoupon.Audience.PAID,
            author_ids=None if favorites_only else paid_source_ids,
            favorites_user=request.user if favorites_only else None,
        ),
        selected_capper=selected_capper,
        selected_sport=None,
        only_live=only_live,
        only_today=only_today,
        match_scope=active_match_scope,
    )
    free_count_queryset = free_meta_queryset
    paid_count_queryset = paid_meta_queryset
    sport_count_querysets = (
        (paid_meta_queryset,) if is_paid_predictions_tab
        else (free_meta_queryset,) if is_vip_predictions_tab
        else (free_meta_queryset, paid_meta_queryset)
    )
    sport_counts_by_code, _sport_single_total = prediction_sport_counts(
        tuple(queryset.exclude(coupon_type=PredictionCoupon.CouponType.EXPRESS) for queryset in sport_count_querysets),
        active_status=active_status,
    )
    sport_total_count = sum(
        apply_prediction_status(queryset, active_status).values("id").distinct().count()
        for queryset in sport_count_querysets
    )
    express_count = sum(
        apply_prediction_status(
            queryset.filter(coupon_type=PredictionCoupon.CouponType.EXPRESS),
            active_status,
        )
        .values("id")
        .distinct()
        .count()
        for queryset in sport_count_querysets
    )
    sport_filter_tabs = build_sport_filter_tabs(
        request,
        active_sport=selected_sport,
        active_express=active_express,
        counts_by_code=sport_counts_by_code,
        total_count=sport_total_count,
        include_express=True,
        express_count=express_count,
    )
    if active_express:
        free_count_queryset = free_count_queryset.filter(
            coupon_type=PredictionCoupon.CouponType.EXPRESS
        )
        paid_count_queryset = paid_count_queryset.filter(
            coupon_type=PredictionCoupon.CouponType.EXPRESS
        )
    elif selected_sport:
        free_count_queryset = free_count_queryset.filter(
            predictions__match__sport=selected_sport
        ).distinct()
        paid_count_queryset = paid_count_queryset.filter(
            predictions__match__sport=selected_sport
        ).distinct()

    count_signature = (
        *feed_source_signature,
        selected_sport.pk if selected_sport else None,
        active_express,
        prediction_type_context["active_prediction_type"],
    )
    count_keys = ("total", "pending", "win", "lose", "refund")
    free_counts = _feed_counts(
        free_count_queryset,
        cache_key=_feed_cache_key(request.user.pk, "free-counts", *count_signature),
    )
    paid_counts = _feed_counts(
        paid_count_queryset,
        cache_key=_feed_cache_key(request.user.pk, "paid-counts", *count_signature),
    )
    if is_paid_predictions_tab:
        counts = paid_counts
    elif is_vip_predictions_tab:
        counts = free_counts
    else:
        counts = {
            key: (free_counts.get(key) or 0) + (paid_counts.get(key) or 0)
            for key in count_keys
        }
    status_tabs = _status_tabs(request, counts, active_status)

    # All formats share one paginated list; discovery does not grant paid access.
    if is_paid_predictions_tab:
        source_filter = Q(pk__in=paid_count_queryset.values("pk"))
    elif is_vip_predictions_tab:
        source_filter = Q(pk__in=free_count_queryset.values("pk"))
    else:
        source_filter = Q(pk__in=free_count_queryset.values("pk")) | Q(pk__in=paid_count_queryset.values("pk"))
    queryset = _published_queryset(include_paid=True).filter(source_filter)
    if favorites_only:
        queryset = queryset.filter(favorites__user=request.user).distinct()
    queryset = apply_prediction_status(queryset, active_status)
    queryset = _sort_prediction_queryset(
        queryset, active_sort,
        default_ordering=("-favorites__created_at", "-created_at") if favorites_only else ("-published_at", "-created_at"),
        popular_ordering=("-likes_count", "-favorites_count", "-published_at", "-created_at"),
    )
    feed_total_count = _feed_status_count(counts, active_status)
    paginator = Paginator(queryset, PREDICTIONS_PAGE_SIZE)
    paginator.__dict__["count"] = feed_total_count
    page_obj = paginator.get_page(request.GET.get("page"))
    page_obj.object_list = _decorate_predictions(request, page_obj.object_list, following_ids=following_ids)
    _attach_paid_catalog_access(page_obj.object_list, request)

    params_without_page = request.GET.copy()
    params_without_page.pop("page", None)
    pagination_query = params_without_page.urlencode()

    active_filter_count = sum(
        [
            bool(selected_capper),
            bool(selected_sport),
            only_live,
            only_today,
            active_match_scope != "all",
            active_express,
            favorites_only,
            active_status != "all",
        ]
    )
    favorites_params = request.GET.copy()
    favorites_params.pop("page", None)
    if favorites_only:
        favorites_params.pop("favorites", None)
    else:
        favorites_params["favorites"] = "1"
    favorites_filter_url = _feed_url(request, favorites_params)

    head_title_main = "Избранные" if favorites_only else "Моя лента"
    head_title_rest = "прогнозы" if favorites_only else "прогнозов"
    head_lede = (
        "Сохраненные прогнозы с быстрыми фильтрами по видам спорта и статусам."
        if favorites_only
        else "Прогнозы от капперов, на которых вы подписаны, с быстрыми фильтрами по видам спорта и статусам."
    )
    head_count_context = "в избранном" if favorites_only else "в ленте"

    return render(
        request,
        "front/following_feed.html",
        {
            "page_obj": page_obj,
            "following": following,
            "vip_stories": vip_stories,
            "vip_stories_count": vip_stories_count,
            "vip_stories_count_label": f"{vip_stories_count} {plural_ru(vip_stories_count, 'эксперт', 'эксперта', 'экспертов')}",
            "vip_ranking_url": reverse("front:cappers_table_group", args=["vip"]),
            "vip_prediction_rail": build_vip_prediction_rail_context(),
            "paid_subscriptions": paid_subscriptions,
            "has_feed_sources": bool(following or paid_subscriptions or vip_stories or favorites_only or feed_total_count),
            "has_personal_feed_sources": bool(following or paid_subscriptions or favorites_only or feed_total_count),
            "following_count": len(following),
            "paid_subscriptions_count": len(paid_subscriptions),
            "feed_total_count": feed_total_count,
            "feed_predictions_count": paginator.count,
            "sport_filter_tabs": sport_filter_tabs,
            "prediction_head": build_prediction_head(
                request,
                title_main=head_title_main,
                title_rest=head_title_rest,
                lede=head_lede,
                total_count=feed_total_count,
                count_context=head_count_context,
                sport_tabs=sport_filter_tabs,
                status_tabs=status_tabs,
                prediction_type_tabs=prediction_type_context["prediction_type_tabs"],
                active_sort=active_sort,
                sort_options=FEED_SORT_OPTIONS,
                show_content_view_switcher=True,
            ),
            "status_tabs": status_tabs,
            "active_status": active_status,
            "active_sort": active_sort,
            "sort_options": FEED_SORT_OPTIONS,
            "selected_capper": selected_capper,
            "only_live": only_live,
            "only_today": only_today,
            "active_match_scope": active_match_scope,
            "favorites_only": favorites_only,
            "favorites_filter_url": favorites_filter_url,
            "pagination_query": pagination_query,
            "active_filter_count": active_filter_count,
            "filter_action_url": prediction_type_context["prediction_type_reset_url"],
            "mobile_filter_tabs": build_mobile_prediction_filter_tabs(
                request,
                reset_url=prediction_type_context["prediction_type_reset_url"],
            ),
            "mobile_match_scope_tabs": build_mobile_prediction_match_scope_tabs(request),
            "mobile_favorites_filter": {
                "href": favorites_filter_url,
                "active": favorites_only,
                "label": "Избранные",
            },
            "adv_placement": "sidebar",
            "predictions_filter_collapsed": prediction_filter_collapsed(request),
            **prediction_type_context,
        },
    )
