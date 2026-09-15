from __future__ import annotations

from typing import Iterable

from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Case, F, PositiveIntegerField, Value, When
from django.utils import timezone

from cabinet.comments.models import Comment
from game.models import Match, Prediction, PredictionCoupon
from notifications.models import MatchWatch

from .metric_models import MatchMetrics, PredictionMetrics
from .models import PredictionFavorite, PredictionLike


PUBLISHED_COMMENT_STATUS = Comment.Status.PUBLISHED


def get_prediction_metrics(coupon_id: int) -> PredictionMetrics:
    metrics, _ = PredictionMetrics.objects.get_or_create(coupon_id=coupon_id)
    return metrics


def get_match_metrics(match_id: int) -> MatchMetrics:
    metrics, _ = MatchMetrics.objects.get_or_create(match_id=match_id)
    return metrics


def refresh_prediction_metrics(coupon_id: int) -> PredictionMetrics | None:
    if not PredictionCoupon.objects.filter(pk=coupon_id).exists():
        PredictionMetrics.objects.filter(coupon_id=coupon_id).delete()
        return None

    content_type = ContentType.objects.get_for_model(
        PredictionCoupon,
        for_concrete_model=False,
    )
    likes_count = PredictionLike.objects.filter(prediction_id=coupon_id).count()
    favorites_count = PredictionFavorite.objects.filter(prediction_id=coupon_id).count()
    comments_count = Comment.objects.filter(
        content_type=content_type,
        object_id=coupon_id,
        status=PUBLISHED_COMMENT_STATUS,
        parent__isnull=True,
    ).count()

    with transaction.atomic():
        metrics = get_prediction_metrics(coupon_id)
        PredictionMetrics.objects.filter(pk=metrics.pk).update(
            likes_count=likes_count,
            favorites_count=favorites_count,
            comments_count=comments_count,
            updated_at=timezone.now(),
        )
        metrics.refresh_from_db()
    return metrics


def refresh_match_metrics(match_id: int) -> MatchMetrics | None:
    if not Match.objects.filter(pk=match_id).exists():
        MatchMetrics.objects.filter(match_id=match_id).delete()
        return None

    content_type = ContentType.objects.get_for_model(Match, for_concrete_model=False)
    predictions_count = (
        Prediction.objects.filter(
            match_id=match_id,
            coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            coupon__audience=PredictionCoupon.Audience.FREE,
        )
        .values("coupon_id")
        .distinct()
        .count()
    )
    comments_count = Comment.objects.filter(
        content_type=content_type,
        object_id=match_id,
        status=PUBLISHED_COMMENT_STATUS,
        parent__isnull=True,
    ).count()
    favorites_count = MatchWatch.objects.filter(match_id=match_id).count()
    activity_count = predictions_count + comments_count + favorites_count

    with transaction.atomic():
        metrics = get_match_metrics(match_id)
        MatchMetrics.objects.filter(pk=metrics.pk).update(
            predictions_count=predictions_count,
            comments_count=comments_count,
            favorites_count=favorites_count,
            activity_count=activity_count,
            updated_at=timezone.now(),
        )
        metrics.refresh_from_db()
    return metrics


def refresh_match_metrics_for_coupon(coupon_id: int) -> None:
    match_ids = (
        Prediction.objects.filter(coupon_id=coupon_id)
        .order_by()
        .values_list("match_id", flat=True)
        .distinct()
    )
    refresh_match_metrics_many(match_ids)


def refresh_match_metrics_many(match_ids: Iterable[int]) -> None:
    for match_id in {int(value) for value in match_ids if value}:
        refresh_match_metrics(match_id)


def increment_prediction_comments(coupon_id: int) -> PredictionMetrics:
    return _change_prediction_counter(coupon_id, "comments_count", 1)


def decrement_prediction_comments(coupon_id: int) -> PredictionMetrics:
    return _change_prediction_counter(coupon_id, "comments_count", -1)


def increment_prediction_likes(coupon_id: int) -> PredictionMetrics:
    return _change_prediction_counter(coupon_id, "likes_count", 1)


def decrement_prediction_likes(coupon_id: int) -> PredictionMetrics:
    return _change_prediction_counter(coupon_id, "likes_count", -1)


def increment_prediction_favorites(coupon_id: int) -> PredictionMetrics:
    return _change_prediction_counter(coupon_id, "favorites_count", 1)


def decrement_prediction_favorites(coupon_id: int) -> PredictionMetrics:
    return _change_prediction_counter(coupon_id, "favorites_count", -1)


def increment_prediction_views(coupon_id: int) -> PredictionMetrics:
    return _change_prediction_counter(coupon_id, "views_count", 1)


def increment_prediction_shares(coupon_id: int) -> PredictionMetrics:
    return _change_prediction_counter(coupon_id, "shares_count", 1)


def increment_match_comments(match_id: int) -> MatchMetrics:
    return _change_match_counter(match_id, "comments_count", 1, affects_activity=True)


def decrement_match_comments(match_id: int) -> MatchMetrics:
    return _change_match_counter(match_id, "comments_count", -1, affects_activity=True)


def increment_match_favorites(match_id: int) -> MatchMetrics:
    return _change_match_counter(match_id, "favorites_count", 1, affects_activity=True)


def decrement_match_favorites(match_id: int) -> MatchMetrics:
    return _change_match_counter(match_id, "favorites_count", -1, affects_activity=True)


def increment_match_views(match_id: int) -> MatchMetrics:
    return _change_match_counter(match_id, "views_count", 1)


def increment_match_shares(match_id: int) -> MatchMetrics:
    return _change_match_counter(match_id, "shares_count", 1)


def toggle_prediction_like_metric(
    prediction: PredictionCoupon,
    user,
) -> tuple[bool, PredictionMetrics]:
    with transaction.atomic():
        metrics = _locked_prediction_metrics(prediction.pk)
        reaction, created = PredictionLike.objects.get_or_create(
            prediction=prediction,
            user=user,
        )
        if created:
            _update_counter(
                PredictionMetrics,
                metrics.pk,
                "likes_count",
                1,
            )
        else:
            reaction.delete()
            _update_counter(
                PredictionMetrics,
                metrics.pk,
                "likes_count",
                -1,
            )
        metrics.refresh_from_db()
    return created, metrics


def toggle_prediction_favorite_metric(
    prediction: PredictionCoupon,
    user,
) -> tuple[bool, PredictionMetrics]:
    with transaction.atomic():
        metrics = _locked_prediction_metrics(prediction.pk)
        favorite, created = PredictionFavorite.objects.get_or_create(
            prediction=prediction,
            user=user,
        )
        if created:
            _update_counter(
                PredictionMetrics,
                metrics.pk,
                "favorites_count",
                1,
            )
        else:
            favorite.delete()
            _update_counter(
                PredictionMetrics,
                metrics.pk,
                "favorites_count",
                -1,
            )
        metrics.refresh_from_db()
    return created, metrics


def toggle_match_favorite_metric(match: Match, user) -> tuple[bool, MatchMetrics]:
    with transaction.atomic():
        metrics = _locked_match_metrics(match.pk)
        watch = MatchWatch.objects.select_for_update().filter(
            user=user,
            match=match,
        ).first()
        if watch is None:
            MatchWatch.objects.create(user=user, match=match)
            watching = True
            _update_match_counter_locked(metrics.pk, "favorites_count", 1, True)
        else:
            watch.delete()
            watching = False
            _update_match_counter_locked(metrics.pk, "favorites_count", -1, True)
        metrics.refresh_from_db()
    return watching, metrics


def _change_prediction_counter(
    coupon_id: int,
    field_name: str,
    delta: int,
) -> PredictionMetrics:
    with transaction.atomic():
        metrics = _locked_prediction_metrics(coupon_id)
        _update_counter(PredictionMetrics, metrics.pk, field_name, delta)
        metrics.refresh_from_db()
    return metrics


def _change_match_counter(
    match_id: int,
    field_name: str,
    delta: int,
    *,
    affects_activity: bool = False,
) -> MatchMetrics:
    with transaction.atomic():
        metrics = _locked_match_metrics(match_id)
        _update_match_counter_locked(
            metrics.pk,
            field_name,
            delta,
            affects_activity,
        )
        metrics.refresh_from_db()
    return metrics


def _locked_prediction_metrics(coupon_id: int) -> PredictionMetrics:
    get_prediction_metrics(coupon_id)
    return PredictionMetrics.objects.select_for_update().get(coupon_id=coupon_id)


def _locked_match_metrics(match_id: int) -> MatchMetrics:
    get_match_metrics(match_id)
    return MatchMetrics.objects.select_for_update().get(match_id=match_id)


def _update_match_counter_locked(
    metrics_pk: int,
    field_name: str,
    delta: int,
    affects_activity: bool,
) -> None:
    updates = {
        field_name: _counter_expression(field_name, delta),
        "updated_at": timezone.now(),
    }
    if affects_activity:
        updates["activity_count"] = _counter_expression("activity_count", delta)
    MatchMetrics.objects.filter(pk=metrics_pk).update(**updates)


def _update_counter(model, metrics_pk: int, field_name: str, delta: int) -> None:
    model.objects.filter(pk=metrics_pk).update(
        **{
            field_name: _counter_expression(field_name, delta),
            "updated_at": timezone.now(),
        }
    )


def _counter_expression(field_name: str, delta: int):
    if delta >= 0:
        return F(field_name) + Value(delta)
    return Case(
        When(**{f"{field_name}__gt": 0}, then=F(field_name) - Value(abs(delta))),
        default=Value(0),
        output_field=PositiveIntegerField(),
    )


__all__ = [
    "decrement_match_comments",
    "decrement_match_favorites",
    "decrement_prediction_comments",
    "decrement_prediction_favorites",
    "decrement_prediction_likes",
    "get_match_metrics",
    "get_prediction_metrics",
    "increment_match_comments",
    "increment_match_favorites",
    "increment_match_shares",
    "increment_match_views",
    "increment_prediction_comments",
    "increment_prediction_favorites",
    "increment_prediction_likes",
    "increment_prediction_shares",
    "increment_prediction_views",
    "refresh_match_metrics",
    "refresh_match_metrics_for_coupon",
    "refresh_match_metrics_many",
    "refresh_prediction_metrics",
    "toggle_match_favorite_metric",
    "toggle_prediction_favorite_metric",
    "toggle_prediction_like_metric",
]
