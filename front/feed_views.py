from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie

from cabinet.models import AnalystFollow, AnalystPaidSubscription, AnalystProfile, DailyTask, User
from cabinet.services.daily_tasks import record_daily_task_action
from cabinet.vip import annotate_vip_status, attach_vip_status_to_user
from game.models import PredictionCoupon, Sport

from .prediction_catalog_views import build_prediction_type_context
from .prediction_views import (
    PREDICTIONS_PAGE_SIZE,
    _decorate_predictions,
    _published_queryset,
    _status_tabs,
    prediction_filter_collapsed,
)
from .sport_tabs import build_sport_filter_tabs
from .views import PREDICTION_STATUS_FILTERS


FEED_SORT_OPTIONS = (
    ("new", "Новые"),
    ("popular", "Популярные"),
)
PAID_FEED_LIMIT = 12
VIP_STORIES_LIMIT = 30
FEED_META_CACHE_TTL = 60


def _feed_cache_key(user_id: int, namespace: str, *parts) -> str:
    import hashlib

    signature = hashlib.sha1(repr(parts).encode("utf-8")).hexdigest()[:20]
    return f"front:feed:{namespace}:v3:{user_id}:{signature}"


def _feed_url(request, params) -> str:
    query = params.urlencode()
    return f"{request.path}?{query}" if query else request.path


def _vip_story_payloads(limit: int = VIP_STORIES_LIMIT) -> list[dict]:
    queryset = annotate_vip_status(
        AnalystProfile.objects.filter(
            is_public=True,
            user__role=User.Role.ANALYST,
        ).select_related("user"),
        user_outer_ref="user_id",
        activated_annotation_name="vip_subscription_activated_at",
    ).filter(is_vip_active=True)

    stories = []
    for profile in queryset.order_by("-vip_subscription_activated_at", "-user_id")[:limit]:
        user = profile.user
        name = profile.display_name or user.get_full_name() or user.username
        avatar_url = ""
        if profile.avatar:
            avatar_url = profile.avatar.url
        elif user.avatar:
            avatar_url = user.avatar.url
        stories.append(
            {
                "id": user.pk,
                "name": name,
                "username": user.username,
                "initial": (name or user.username or "К")[0].upper(),
                "avatar_url": avatar_url,
                "profile_url": reverse(
                    "front:expert_profile",
                    kwargs={"username": user.username},
                ),
                "vip_activated_at": getattr(profile, "vip_subscription_activated_at", None),
                "vip_ends_at": getattr(profile, "vip_ends_at", None),
            }
        )
    return stories


def _sport_from_filter(value: str) -> Sport | None:
    if not value:
        return None
    queryset = Sport.objects.all()
    if value.isdigit():
        return queryset.filter(pk=int(value)).first()
    return queryset.filter(code__iexact=value).first()


def _feed_meta_queryset(*, audience: str, author_ids) -> object:
    """Cheap coupon queryset for tabs/counts without card annotations or ROI subqueries."""
    return PredictionCoupon.objects.filter(
        published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        audience=audience,
        author_id__in=author_ids,
    )

def _apply_feed_filters(queryset, *, selected_capper, selected_sport, only_live, only_today):
    if selected_capper:
        queryset = queryset.filter(author__username=selected_capper)
    if selected_sport:
        queryset = queryset.filter(predictions__match__sport=selected_sport)
    if only_live:
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


def _feed_author_counts(
    user_id: int,
    *,
    following_ids: set[int],
    paid_upgrade_ids: list[int],
    prediction_format: str,
) -> tuple[dict[int, int], dict[int, int]]:
    cache_key = _feed_cache_key(
        user_id,
        "author-counts",
        tuple(sorted(following_ids)),
        tuple(sorted(paid_upgrade_ids)),
        prediction_format,
    )
    cached = cache.get(cache_key)
    if cached is not None:
        return cached["author_counts"], cached["locked_paid_counts"]

    locked_paid_counts = {
        row["author_id"]: row["total"]
        for row in PredictionCoupon.objects.filter(
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            audience=PredictionCoupon.Audience.PAID,
            author_id__in=paid_upgrade_ids,
            prediction_format=prediction_format,
        )
        .values("author_id")
        .annotate(total=Count("id"))
    }
    author_counts = {
        row["author_id"]: row["total"]
        for row in PredictionCoupon.objects.filter(
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            audience=PredictionCoupon.Audience.FREE,
            author_id__in=following_ids,
            prediction_format=prediction_format,
        )
        .values("author_id")
        .annotate(total=Count("id"))
    }
    cache.set(
        cache_key,
        {
            "author_counts": author_counts,
            "locked_paid_counts": locked_paid_counts,
        },
        FEED_META_CACHE_TTL,
    )
    return author_counts, locked_paid_counts


@login_required
@ensure_csrf_cookie
def following_feed(request):
    record_daily_task_action(request.user, DailyTask.TaskType.OPEN_FEED)
    prediction_type_context = build_prediction_type_context(request)
    prediction_format = prediction_type_context["prediction_format"]

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
    paid_usernames = {subscription.analyst.username for subscription in paid_subscriptions}
    vip_stories = _vip_story_payloads()

    selected_capper = request.GET.get("capper", "").strip()
    if selected_capper and selected_capper not in followed_usernames | paid_usernames:
        selected_capper = ""

    selected_sport = _sport_from_filter(request.GET.get("sport", "").strip())
    only_live = request.GET.get("live") == "1"
    only_today = request.GET.get("today") == "1"

    feed_source_signature = (
        tuple(sorted(following_ids)),
        tuple(sorted(paid_analyst_ids)),
        selected_capper,
        only_live,
        only_today,
    )

    # Metadata (tabs/counts) intentionally uses lightweight querysets. The full
    # card queryset contains ROI annotations/selects/prefetches and is much more
    # expensive to aggregate over.
    free_meta_queryset = _apply_feed_filters(
        _feed_meta_queryset(
            audience=PredictionCoupon.Audience.FREE,
            author_ids=following_ids,
        ).filter(prediction_format=prediction_format),
        selected_capper=selected_capper,
        selected_sport=None,
        only_live=only_live,
        only_today=only_today,
    )
    paid_meta_queryset = _apply_feed_filters(
        _feed_meta_queryset(
            audience=PredictionCoupon.Audience.PAID,
            author_ids=paid_analyst_ids,
        ).filter(prediction_format=prediction_format),
        selected_capper=selected_capper,
        selected_sport=None,
        only_live=only_live,
        only_today=only_today,
    )
    sport_filter_tabs = build_sport_filter_tabs(request, active_sport=selected_sport)

    free_count_queryset = free_meta_queryset
    paid_count_queryset = paid_meta_queryset
    if selected_sport:
        free_count_queryset = free_count_queryset.filter(
            predictions__match__sport=selected_sport
        ).distinct()
        paid_count_queryset = paid_count_queryset.filter(
            predictions__match__sport=selected_sport
        ).distinct()

    count_signature = (
        *feed_source_signature,
        selected_sport.pk if selected_sport else None,
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
    counts = {
        key: (free_counts.get(key) or 0) + (paid_counts.get(key) or 0)
        for key in count_keys
    }

    # Full querysets are evaluated only for the cards that will actually render.
    queryset = _apply_feed_filters(
        _published_queryset().filter(
            author_id__in=following_ids,
            prediction_format=prediction_format,
        ),
        selected_capper=selected_capper,
        selected_sport=selected_sport,
        only_live=only_live,
        only_today=only_today,
    )
    paid_queryset = _apply_feed_filters(
        _published_queryset(include_paid=True).filter(
            audience=PredictionCoupon.Audience.PAID,
            author_id__in=paid_analyst_ids,
            prediction_format=prediction_format,
        ),
        selected_capper=selected_capper,
        selected_sport=selected_sport,
        only_live=only_live,
        only_today=only_today,
    )

    if active_status == "pending":
        queryset = queryset.filter(state_status=PredictionCoupon.StateStatus.PENDING)
    elif active_status != "all":
        queryset = queryset.filter(state_status=active_status)
    if active_status == "pending":
        paid_queryset = paid_queryset.filter(state_status=PredictionCoupon.StateStatus.PENDING)
    elif active_status != "all":
        paid_queryset = paid_queryset.filter(state_status=active_status)

    if active_sort == "popular":
        queryset = queryset.order_by(
            "-likes_count",
            "-favorites_count",
            "-published_at",
            "-created_at",
        )
        paid_queryset = paid_queryset.order_by(
            "-likes_count",
            "-favorites_count",
            "-published_at",
            "-created_at",
        )
    else:
        queryset = queryset.order_by("-published_at", "-created_at")
        paid_queryset = paid_queryset.order_by("-published_at", "-created_at")

    free_predictions_count = _feed_status_count(free_counts, active_status)
    paginator = Paginator(queryset, PREDICTIONS_PAGE_SIZE)
    # Paginator otherwise calls COUNT() on the fully annotated card queryset.
    # We already have the exact count from the lightweight cached aggregate.
    paginator.__dict__["count"] = free_predictions_count
    page_obj = paginator.get_page(request.GET.get("page"))
    free_coupons = list(page_obj.object_list)
    paid_coupons = list(paid_queryset[:PAID_FEED_LIMIT])
    decorated = _decorate_predictions(
        request,
        [*free_coupons, *paid_coupons],
        following_ids=following_ids,
    )
    decorated_by_id = {card.id: card for card in decorated}
    page_obj.object_list = [
        decorated_by_id[coupon.pk]
        for coupon in free_coupons
        if coupon.pk in decorated_by_id
    ]
    paid_predictions = [
        decorated_by_id[coupon.pk]
        for coupon in paid_coupons
        if coupon.pk in decorated_by_id
    ]
    paid_predictions_count = _feed_status_count(paid_counts, active_status)

    paid_upgrade_follows = [
        follow
        for follow in following
        if follow.analyst_id not in paid_analyst_ids
        and getattr(follow.analyst, "analyst_profile", None) is not None
        and follow.analyst.analyst_profile.paid_predictions_enabled
        and follow.analyst.analyst_profile.paid_predictions_price > 0
        and (not selected_capper or follow.analyst.username == selected_capper)
    ]
    paid_upgrade_ids = [follow.analyst_id for follow in paid_upgrade_follows]
    author_counts, locked_paid_counts = _feed_author_counts(
        request.user.pk,
        following_ids=following_ids,
        paid_upgrade_ids=paid_upgrade_ids,
        prediction_format=prediction_format,
    )
    paid_upgrade_follows = [
        follow
        for follow in paid_upgrade_follows
        if locked_paid_counts.get(follow.analyst_id, 0)
    ]

    capper_params = request.GET.copy()
    capper_params.pop("page", None)
    capper_params.pop("capper", None)
    feed_all_cappers_url = _feed_url(request, capper_params)

    for follow in following:
        profile = getattr(follow.analyst, "analyst_profile", None)
        follow.feed_name = (
            profile.display_name
            if profile and profile.display_name
            else follow.analyst.get_full_name() or follow.analyst.username
        )
        follow.feed_avatar_url = profile.avatar.url if profile and profile.avatar else ""
        follow.feed_trust_index = profile.trust_index if profile else 0
        follow.feed_initial = (follow.feed_name or follow.analyst.username or "К")[0].upper()
        follow.feed_predictions_count = author_counts.get(follow.analyst_id, 0)
        follow.feed_locked_paid_count = locked_paid_counts.get(follow.analyst_id, 0)
        follow.feed_profile_url = reverse(
            "front:expert_profile",
            kwargs={"username": follow.analyst.username},
        )

        follow_params = capper_params.copy()
        follow_params["capper"] = follow.analyst.username
        follow.feed_filter_url = _feed_url(request, follow_params)

    feed_all_cappers_count = sum(author_counts.values())
    params_without_page = request.GET.copy()
    params_without_page.pop("page", None)
    pagination_query = params_without_page.urlencode()

    active_filter_count = sum(
        [
            bool(selected_capper),
            bool(selected_sport),
            only_live,
            only_today,
            active_status != "all",
        ]
    )

    return render(
        request,
        "front/following_feed.html",
        {
            "page_obj": page_obj,
            "following": following,
            "vip_stories": vip_stories,
            "vip_ranking_url": reverse("front:cappers_table_group", args=["vip"]),
            "paid_subscriptions": paid_subscriptions,
            "has_feed_sources": bool(following or paid_subscriptions or vip_stories),
            "following_count": len(following),
            "paid_subscriptions_count": len(paid_subscriptions),
            "paid_predictions": paid_predictions,
            "paid_predictions_count": paid_predictions_count,
            "paid_upgrade_offers": paid_upgrade_follows,
            "paid_upgrade_offers_count": len(paid_upgrade_follows),
            "feed_total_count": paginator.count + paid_predictions_count,
            "feed_predictions_count": paginator.count,
            "sport_filter_tabs": sport_filter_tabs,
            "status_tabs": _status_tabs(request, counts, active_status),
            "active_status": active_status,
            "active_sort": active_sort,
            "sort_options": FEED_SORT_OPTIONS,
            "selected_capper": selected_capper,
            "only_live": only_live,
            "only_today": only_today,
            "pagination_query": pagination_query,
            "active_filter_count": active_filter_count,
            "feed_all_cappers_url": feed_all_cappers_url,
            "feed_all_cappers_count": feed_all_cappers_count,
            "filter_action_url": prediction_type_context["prediction_type_reset_url"],
            "adv_placement": "sidebar",
            "hide_footer": True,
            "predictions_filter_collapsed": prediction_filter_collapsed(request),
            **prediction_type_context,
        },
    )
