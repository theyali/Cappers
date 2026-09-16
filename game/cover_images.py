import random

from django.core.cache import cache

from .models import PredictionCoupon, PredictionCoverImage


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


def assign_coupon_cover_image(coupon: PredictionCoupon) -> int | None:
    """Assign a cover without repeating the same active-cover lookup for bulk publishes."""
    if coupon.cover_image_id:
        return coupon.cover_image_id

    predictions = list(
        coupon.predictions.select_related("match__sport").order_by("id")
    )
    if not predictions:
        return None

    if len(predictions) > 1 or coupon.coupon_type == PredictionCoupon.CouponType.EXPRESS:
        cover_type = PredictionCoverImage.CoverType.EXPRESS
        sport_id = None
    else:
        sport_id = predictions[0].match.sport_id
        if not sport_id:
            return None
        cover_type = PredictionCoverImage.CoverType.SPORT

    cover_ids = active_cover_ids(
        cover_type=cover_type,
        placement=PredictionCoverImage.Placement.GRID,
        sport_id=sport_id,
    )
    if not cover_ids:
        return None

    cover_id = random.choice(cover_ids)
    PredictionCoupon.objects.filter(pk=coupon.pk, cover_image_id__isnull=True).update(
        cover_image_id=cover_id
    )
    coupon.cover_image_id = cover_id
    return cover_id
