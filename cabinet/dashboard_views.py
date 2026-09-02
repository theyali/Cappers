from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Prefetch, Q
from django.shortcuts import redirect
from django.utils import timezone

from front.models import PredictionFavorite, PredictionLike
from game.models import Match, Prediction, PredictionCoupon

from .confidence_calibration import build_confidence_calibration
from .models import AnalystFollow


SETTLED_COUPON_STATES = (
    PredictionCoupon.StateStatus.WIN,
    PredictionCoupon.StateStatus.LOSE,
    PredictionCoupon.StateStatus.REFUND,
)


def _today_bounds():
    now = timezone.localtime()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return now, start, start + timedelta(days=1)


def _coupon_profit(coupon: PredictionCoupon) -> Decimal:
    stake = coupon.total_stake or Decimal("0")
    if coupon.state_status == PredictionCoupon.StateStatus.WIN:
        return (coupon.possible_payout or Decimal("0")) - stake
    if coupon.state_status == PredictionCoupon.StateStatus.LOSE:
        return -stake
    return Decimal("0")


def _signed_percent(value: Decimal) -> str:
    prefix = "+" if value > 0 else ""
    return f"{prefix}{value.quantize(Decimal('0.1'))}%"


def _confidence_recommendation(calibration: dict) -> dict:
    if not calibration["has_data"]:
        return {
            "tone": "neutral",
            "title": "Нужна история рассчитанных купонов",
            "text": "После первых выигрышей и проигрышей здесь появится разбор того, насколько заявленная уверенность совпадает с фактом.",
        }

    if not calibration["has_reliable_data"]:
        return {
            "tone": "warning",
            "title": "Выборка пока мала",
            "text": f"Для устойчивой оценки нужно минимум {calibration['min_reliable_sample']} рассчитанных купонов в бакете.",
        }

    average_delta = Decimal(str(calibration["average_delta"]))
    if average_delta <= Decimal("-5"):
        return {
            "tone": "danger",
            "title": "Уверенность завышается",
            "text": "Фактический проход ниже заявленной уверенности. Стоит строже оценивать риск перед публикацией купона.",
        }
    if average_delta >= Decimal("5"):
        return {
            "tone": "success",
            "title": "Уверенность занижается",
            "text": "Фактический проход выше заявленной уверенности. Можно увереннее маркировать сильные прогнозы.",
        }
    return {
        "tone": "success",
        "title": "Оценка близка к факту",
        "text": "Заявленная уверенность в среднем совпадает с фактическим проходом по рассчитанным купонам.",
    }


def _actor_data(user) -> dict:
    profile = getattr(user, "analyst_profile", None)
    display_name = (
        profile.display_name
        if profile and profile.display_name
        else user.get_full_name() or user.username
    )
    return {
        "name": display_name,
        "username": user.username,
        "initial": (display_name or user.username or "П")[0].upper(),
        "avatar_url": profile.avatar.url if profile and profile.avatar else "",
    }


def _reaction_item(reaction, kind: str) -> dict:
    actor = _actor_data(reaction.user)
    prediction = reaction.prediction
    item = (
        prediction.predictions.select_related("match__home_team", "match__away_team")
        .order_by("id")
        .first()
    )
    if item:
        match = item.match
        selection = item.selection
        match_name = f"{match.home_team_name or 'Хозяева'} — {match.away_team_name or 'Гости'}"
        positions_count = prediction.predictions.count()
        if positions_count > 1:
            selection = f"{selection} + ещё {positions_count - 1}"
    else:
        selection = "Прогноз"
        match_name = "Матчи не указаны"

    return {
        **actor,
        "kind": kind,
        "label": "Поставил лайк" if kind == "like" else "Добавил в избранное",
        "icon": "👍" if kind == "like" else "♥",
        "created_at": reaction.created_at,
        "coupon_id": prediction.id,
        "selection": selection,
        "match_name": match_name,
    }


def _live_prediction_cards(analyst) -> list[Prediction]:
    live_items = Prediction.objects.filter(match__sync_scope=Match.SyncScope.LIVE).select_related(
        "coupon__author__analyst_profile",
        "match__league",
        "match__home_team",
        "match__away_team",
    ).order_by("id")
    coupons = list(
        PredictionCoupon.objects.filter(
            author=analyst,
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            predictions__match__sync_scope=Match.SyncScope.LIVE,
        )
        .prefetch_related(Prefetch("predictions", queryset=live_items, to_attr="live_items"))
        .distinct()
        .order_by("-published_at", "-created_at")[:12]
    )

    coupon_ids = [coupon.pk for coupon in coupons]
    liked_ids = set(
        PredictionLike.objects.filter(
            user=analyst,
            prediction_id__in=coupon_ids,
        ).values_list("prediction_id", flat=True)
    )
    favorite_ids = set(
        PredictionFavorite.objects.filter(
            user=analyst,
            prediction_id__in=coupon_ids,
        ).values_list("prediction_id", flat=True)
    )
    actor = _actor_data(analyst)
    analyst_profile = getattr(analyst, "analyst_profile", None)

    cards = []
    for coupon in coupons:
        items = list(getattr(coupon, "live_items", []) or [])
        if not items:
            continue
        item = items[0]
        item.state_status = coupon.state_status
        item.confidence = coupon.confidence
        if coupon.total_stake:
            item.coefficient = (coupon.possible_payout / coupon.total_stake).quantize(Decimal("0.01"))
        if len(items) > 1:
            item.market = f"Экспресс · {coupon.predictions.count()} игр"
            item.selection = f"{item.selection} + другие позиции"

        item.expert_name = actor["name"]
        item.expert_initials = actor["initial"]
        item.expert_avatar_url = actor["avatar_url"]
        item.expert_verified = bool(analyst_profile and analyst_profile.is_verified)
        item.is_liked = coupon.pk in liked_ids
        item.is_favorite = coupon.pk in favorite_ids
        item.is_own = True
        item.is_following_author = False
        cards.append(item)
    return cards


def build_dashboard_context(analyst) -> dict:
    now, today_start, tomorrow_start = _today_bounds()

    published = PredictionCoupon.objects.filter(
        author=analyst,
        published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
    )
    published_coupons = list(published.order_by("settled_at", "updated_at", "id"))
    confidence_calibration = build_confidence_calibration(published_coupons)
    engagement_stats = published.aggregate(
        published_count=Count("id", distinct=True),
        total_likes=Count("likes", distinct=True),
        total_saves=Count("favorites", distinct=True),
    )
    published_count = engagement_stats["published_count"] or 0
    total_likes_count = engagement_stats["total_likes"] or 0
    total_saves_count = engagement_stats["total_saves"] or 0
    avg_likes_per_prediction = round(total_likes_count / published_count, 1) if published_count else 0
    avg_saves_per_prediction = round(total_saves_count / published_count, 1) if published_count else 0

    today_predictions = published.filter(
        predictions__match__starts_at__gte=today_start,
        predictions__match__starts_at__lt=tomorrow_start,
    ).distinct()
    today_stats = today_predictions.aggregate(
        active=Count("id", distinct=True),
        wins=Count(
            "id",
            filter=Q(state_status=PredictionCoupon.StateStatus.WIN),
            distinct=True,
        ),
        losses=Count(
            "id",
            filter=Q(state_status=PredictionCoupon.StateStatus.LOSE),
            distinct=True,
        ),
        pending=Count(
            "id",
            filter=Q(state_status=PredictionCoupon.StateStatus.PENDING),
            distinct=True,
        ),
        live=Count(
            "id",
            filter=Q(predictions__match__sync_scope=Match.SyncScope.LIVE),
            distinct=True,
        ),
    )

    settled_today = list(
        published.filter(
            state_status__in=SETTLED_COUPON_STATES,
            settled_at__gte=today_start,
            settled_at__lt=tomorrow_start,
        ).order_by("settled_at", "id")
    )
    roi_stake = sum(
        (coupon.total_stake or Decimal("0") for coupon in settled_today),
        Decimal("0"),
    )
    roi_profit = sum((_coupon_profit(coupon) for coupon in settled_today), Decimal("0"))
    roi_today = roi_profit / roi_stake * Decimal("100") if roi_stake else Decimal("0")

    followers_today_qs = (
        AnalystFollow.objects.filter(
            analyst=analyst,
            created_at__gte=today_start,
            created_at__lt=tomorrow_start,
        )
        .select_related("follower", "follower__analyst_profile")
        .order_by("-created_at")
    )
    new_followers_count = followers_today_qs.count()
    latest_followers = list(followers_today_qs[:6])
    for follow in latest_followers:
        follow.dashboard_actor = _actor_data(follow.follower)

    likes = list(
        PredictionLike.objects.filter(
            prediction__author=analyst,
            prediction__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        )
        .exclude(user=analyst)
        .select_related("user", "user__analyst_profile", "prediction")
        .order_by("-created_at")[:10]
    )
    favorites = list(
        PredictionFavorite.objects.filter(
            prediction__author=analyst,
            prediction__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
        )
        .exclude(user=analyst)
        .select_related("user", "user__analyst_profile", "prediction")
        .order_by("-created_at")[:10]
    )
    reactions = [
        *(_reaction_item(item, "like") for item in likes),
        *(_reaction_item(item, "favorite") for item in favorites),
    ]
    reactions.sort(key=lambda item: item["created_at"], reverse=True)

    analyst_profile = getattr(analyst, "analyst_profile", None)
    display_name = (
        analyst_profile.display_name
        if analyst_profile and analyst_profile.display_name
        else analyst.get_full_name() or analyst.username
    )

    return {
        "display_name": display_name,
        "today": now.date(),
        "today_stats": today_stats,
        "roi_today": roi_today,
        "roi_today_display": _signed_percent(roi_today),
        "roi_profit": roi_profit,
        "roi_stake": roi_stake,
        "new_followers_count": new_followers_count,
        "latest_followers": latest_followers,
        "latest_reactions": reactions[:10],
        "live_predictions": _live_prediction_cards(analyst),
        "total_likes_count": total_likes_count,
        "total_saves_count": total_saves_count,
        "avg_likes_per_prediction": avg_likes_per_prediction,
        "avg_saves_per_prediction": avg_saves_per_prediction,
        "dashboard_confidence_calibration": confidence_calibration,
        "dashboard_confidence_recommendation": _confidence_recommendation(
            confidence_calibration
        ),
    }


@login_required
def dashboard(request):
    return redirect("cabinet:profile")
