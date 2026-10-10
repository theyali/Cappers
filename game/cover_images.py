import random

from django.core.cache import cache
from django.db.models import Count

from .models import Match, Prediction, PredictionCoupon, PredictionCoverImage


COVER_IDS_CACHE_TTL = 300
COVER_IDS_VERSION_KEY = "prediction-cover-ids:version"


def _cover_ids_version() -> int:
    try:
        cache.add(COVER_IDS_VERSION_KEY, 1, timeout=None)
        return int(cache.get(COVER_IDS_VERSION_KEY) or 1)
    except Exception:
        return 1


def invalidate_cover_ids_cache() -> None:
    try:
        cache.add(COVER_IDS_VERSION_KEY, 1, timeout=None)
        cache.incr(COVER_IDS_VERSION_KEY)
    except Exception:
        # Cache is an optimization only; publication must stay available if Redis is down.
        try:
            cache.set(COVER_IDS_VERSION_KEY, 2, timeout=None)
        except Exception:
            pass


def active_cover_ids(*, cover_type: str, placement: str, sport_id: int | None) -> list[int]:
    version = _cover_ids_version()
    sport_key = sport_id if sport_id is not None else "all"
    cache_key = f"prediction-cover-ids:v{version}:{placement}:{cover_type}:{sport_key}"
    try:
        cached = cache.get(cache_key)
    except Exception:
        cached = None
    if cached is not None:
        return list(cached)

    queryset = PredictionCoverImage.objects.filter(
        cover_type=cover_type,
        placement=placement,
        sport_id=sport_id,
        is_active=True,
    )
    cover_ids = list(queryset.values_list("id", flat=True))
    try:
        cache.set(cache_key, cover_ids, COVER_IDS_CACHE_TTL)
    except Exception:
        pass
    return cover_ids


def _least_used_cover_id(model, cover_ids: list[int], usage: dict[int, int] | None = None) -> int | None:
    if not cover_ids:
        return None
    if usage is None:
        usage = dict(
            model.objects.filter(cover_image_id__in=cover_ids)
            .order_by()
            .values_list("cover_image_id")
            .annotate(count=Count("id"))
        )
    least = min(usage.get(cover_id, 0) for cover_id in cover_ids)
    choices = [cover_id for cover_id in cover_ids if usage.get(cover_id, 0) == least]
    cover_id = random.choice(choices)
    usage[cover_id] = usage.get(cover_id, 0) + 1
    return cover_id


def _coupon_cover_ids(coupon: PredictionCoupon) -> list[int]:
    predictions = list(
        coupon.predictions.select_related("match__sport").order_by("id")
    )
    if not predictions:
        return []

    if len(predictions) > 1 or coupon.coupon_type == PredictionCoupon.CouponType.EXPRESS:
        return active_cover_ids(
            cover_type=PredictionCoverImage.CoverType.EXPRESS,
            placement=PredictionCoverImage.Placement.GRID,
            sport_id=None,
        )

    sport_id = predictions[0].match.sport_id
    if not sport_id:
        return []
    return active_cover_ids(
        cover_type=PredictionCoverImage.CoverType.SPORT,
        placement=PredictionCoverImage.Placement.GRID,
        sport_id=sport_id,
    )


def _prediction_sport_id(prediction: Prediction) -> int | None:
    match = getattr(prediction, "match", None)
    if match is not None:
        return match.sport_id
    if not prediction.match_id:
        return None
    return Match.objects.filter(pk=prediction.match_id).values_list("sport_id", flat=True).first()


def assign_coupon_cover_image(coupon: PredictionCoupon, *, save: bool = True) -> int | None:
    """Assign a cover without repeating the same active-cover lookup for bulk publishes."""
    if coupon.cover_image_id:
        return coupon.cover_image_id

    cover_id = _least_used_cover_id(PredictionCoupon, _coupon_cover_ids(coupon))
    if cover_id is None:
        return None
    if save and coupon.pk:
        PredictionCoupon.objects.filter(pk=coupon.pk, cover_image_id__isnull=True).update(
            cover_image_id=cover_id
        )
    coupon.cover_image_id = cover_id
    return cover_id


def assign_prediction_cover_images(predictions: list[Prediction], *, save: bool = True) -> int:
    """Assign sport covers to prediction events with an even least-used distribution."""
    pending = [prediction for prediction in predictions if not prediction.cover_image_id]
    if not pending:
        return 0

    cover_ids_by_sport: dict[int, list[int]] = {}
    usage_by_sport: dict[int, dict[int, int]] = {}
    changed = []

    for prediction in pending:
        sport_id = _prediction_sport_id(prediction)
        if not sport_id:
            continue
        if sport_id not in cover_ids_by_sport:
            cover_ids_by_sport[sport_id] = active_cover_ids(
                cover_type=PredictionCoverImage.CoverType.SPORT,
                placement=PredictionCoverImage.Placement.GRID,
                sport_id=sport_id,
            )
        cover_ids = cover_ids_by_sport[sport_id]
        if not cover_ids:
            continue
        if sport_id not in usage_by_sport:
            usage_by_sport[sport_id] = dict(
                Prediction.objects.filter(cover_image_id__in=cover_ids)
                .order_by()
                .values_list("cover_image_id")
                .annotate(count=Count("id"))
            )
        cover_id = _least_used_cover_id(Prediction, cover_ids, usage_by_sport[sport_id])
        if cover_id is None:
            continue
        prediction.cover_image_id = cover_id
        changed.append(prediction)

    if save:
        saved = [prediction for prediction in changed if prediction.pk]
        if saved:
            Prediction.objects.bulk_update(saved, ["cover_image"])
    return len(changed)


def assign_prediction_cover_image(prediction: Prediction, *, save: bool = True) -> int | None:
    assigned = assign_prediction_cover_images([prediction], save=save)
    return prediction.cover_image_id if assigned else None
