"""Backgrounds of the coupon cards in the mobile home slider and of the event cards on the coupon page.

The pictures live in static: one folder for single coupons, named by sport
("tennis_B_clay@2x.png"), and one for express coupons. Each coupon and each
event keeps the path it got, and every new one gets the picture of its kind
used least so far, so all of them come up in turn.
"""

import random
from functools import lru_cache
from pathlib import Path

from django.apps import apps
from django.db.models import Count
from django.templatetags.static import static

from game.models import Prediction, PredictionCoupon

SPORT_DIR = "front/img/forecast-card-backgrounds/png@2x"
EXPRESS_DIR = "front/img/express-backgrounds/png@2x"
EXPRESS = "express"
# Sport codes vary by data provider; the first matching word picks the pictures.
SPORT_WORDS = (
    ("basketball", "basketball"),
    ("hockey", "hockey"),
    ("tennis", "tennis"),
    ("football", "football"),
    ("soccer", "football"),
)
# Pictures light enough to need dark text on top.
LIGHT_BACKGROUNDS = {"hockey_B_ice"}


@lru_cache(maxsize=1)
def backgrounds() -> dict[str, list[str]]:
    """Static paths of the pictures by kind: a sport such as "tennis", or "express"."""
    static_root = Path(apps.get_app_config("front").path) / "static"
    found: dict[str, list[str]] = {}
    for folder, by_sport in ((SPORT_DIR, True), (EXPRESS_DIR, False)):
        directory = static_root / folder
        if not directory.is_dir():
            continue
        for picture in sorted(directory.glob("*@2x.png")):
            kind = picture.name.split("_", 1)[0] if by_sport else EXPRESS
            found.setdefault(kind, []).append(f"{folder}/{picture.name}")
    return found


def sport_kind(sport) -> str:
    code = (sport.code if sport else "").lower()
    for word, kind in SPORT_WORDS:
        if word in code and kind in backgrounds():
            return kind
    # A sport without its own pictures gets the mixed ones.
    return EXPRESS


def background_kind(coupon: PredictionCoupon, positions) -> str:
    if len(positions) > 1 or coupon.coupon_type == PredictionCoupon.CouponType.EXPRESS:
        return EXPRESS
    return sport_kind(positions[0].match.sport if positions else None)


def _give_least_used(model, items_with_kind) -> None:
    """Give every item without a valid background the least used one of its kind."""
    pictures = backgrounds()
    known = {path for paths in pictures.values() for path in paths}
    missing = [
        (item, kind)
        for item, kind in items_with_kind
        if item.mobile_card_background not in known and pictures.get(kind)
    ]
    if not missing:
        return

    usage = dict(
        model.objects.filter(mobile_card_background__in=known)
        .order_by()
        .values_list("mobile_card_background")
        .annotate(count=Count("id"))
    )
    for item, kind in missing:
        least = min(usage.get(path, 0) for path in pictures[kind])
        choice = random.choice([path for path in pictures[kind] if usage.get(path, 0) == least])
        usage[choice] = usage.get(choice, 0) + 1
        item.mobile_card_background = choice
    model.objects.bulk_update([item for item, _ in missing], ["mobile_card_background"])


def assign_backgrounds(coupons_with_positions) -> None:
    _give_least_used(
        PredictionCoupon,
        [(coupon, background_kind(coupon, positions)) for coupon, positions in coupons_with_positions],
    )


def assign_event_backgrounds(events) -> None:
    """Events are single matches, so they always get the pictures of their sport."""
    _give_least_used(Prediction, [(event, sport_kind(event.match.sport)) for event in events])


def assign_coupon_backgrounds(coupon: PredictionCoupon) -> None:
    """Pictures for a just published coupon and each of its events."""
    events = list(coupon.predictions.select_related("match__sport"))
    assign_backgrounds([(coupon, events)])
    assign_event_backgrounds(events)


def background_urls(path: str) -> dict:
    """URLs of a background for the card, with the sharper @3x copy when there is one."""
    if not path:
        return {"url": "", "url_3x": "", "is_light": False}
    sharper = path.replace("png@2x", "png@3x").replace("@2x.png", "@3x.png")
    static_root = Path(apps.get_app_config("front").path) / "static"
    name = Path(path).name.removesuffix("@2x.png")
    return {
        "url": static(path),
        "url_3x": static(sharper) if (static_root / sharper).is_file() else "",
        "is_light": name in LIGHT_BACKGROUNDS,
    }
