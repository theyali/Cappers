"""Canonical basket draft selection, versioning and serialization."""
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.utils import timezone

from cabinet.models import User
from game.models import Prediction, PredictionCoupon

DRAFT_SESSION_MAX_AGE_SECONDS = max(int(getattr(settings, "SESSION_COOKIE_AGE", 1209600)), 1)


class CouponDraftConflict(Exception):
    def __init__(self, draft):
        self.draft = serialize_draft_coupon(draft) if draft else None
        self.payload = {"ok": False, "draft_conflict": True, "draft": self.draft,
                        "error": "Купон изменён в другой вкладке. Показано актуальное состояние."}


def check_draft_revision(draft, revision):
    if draft is not None and revision != draft.updated_at.isoformat():
        raise CouponDraftConflict(draft)


def lock_current_draft(user, coupon_id, *, revision=None, check_revision=False):
    # Lock the author first so two tabs cannot both create a new basket.
    User.objects.select_for_update().get(pk=user.pk)
    draft = draft_for_update(user, coupon_id)
    if coupon_id is not None and draft is None:
        raise CouponDraftConflict(active_draft_coupon(user))
    if check_revision:
        check_draft_revision(draft, revision)
    return draft


def draft_for_update(user: User, coupon_id: int | None) -> PredictionCoupon | None:
    delete_expired_draft_coupons(user)
    cutoff = draft_session_cutoff()
    queryset = PredictionCoupon.objects.select_for_update().filter(
        author=user,
        published_status=PredictionCoupon.PublishedStatus.DRAFT,
        prediction_format=PredictionCoupon.PredictionFormat.QUICK,
        updated_at__gte=cutoff,
    )
    if coupon_id is not None:
        return queryset.filter(pk=coupon_id).first()
    return queryset.order_by("-updated_at", "-id").first()


def active_draft_coupon(user: User) -> PredictionCoupon | None:
    delete_expired_draft_coupons(user)
    return (
        PredictionCoupon.objects.filter(
            author=user,
            published_status=PredictionCoupon.PublishedStatus.DRAFT,
            prediction_format=PredictionCoupon.PredictionFormat.QUICK,
            updated_at__gte=draft_session_cutoff(),
        )
        .prefetch_related("predictions__match__sport", "predictions__match__league__country", "predictions__match__home_team", "predictions__match__away_team")
        .order_by("-updated_at", "-id")
        .first()
    )


def draft_session_cutoff():
    return timezone.now() - timedelta(seconds=DRAFT_SESSION_MAX_AGE_SECONDS)


def delete_expired_draft_coupons(user: User) -> int:
    # Drafts that still carry followers' copied stakes (coupons unpublished before
    # that was forbidden) are kept until those stakes are refunded.
    deleted, _ = PredictionCoupon.objects.filter(
        author=user,
        published_status=PredictionCoupon.PublishedStatus.DRAFT,
        updated_at__lt=draft_session_cutoff(),
        copied_bets__isnull=True,
    ).delete()
    return deleted


def serialize_draft_coupon(coupon: PredictionCoupon) -> dict:
    predictions = list(coupon.predictions.all())
    stake = coupon.total_stake if coupon.total_stake and coupon.total_stake > 0 else None

    return {
        "id": coupon.id,
        "revision": coupon.updated_at.isoformat(),
        "stake": _decimal_string(stake) if stake is not None else "",
        "confidence": coupon.confidence,
        "audience": coupon.audience,
        "tournament_id": coupon.tournament_id,
        "items": [_serialize_prediction(prediction) for prediction in predictions],
    }


def _serialize_prediction(prediction: Prediction) -> dict:
    match = prediction.match
    starts_at = (
        timezone.localtime(match.starts_at).strftime("%d.%m %H:%M")
        if match.starts_at
        else "Время не указано"
    )
    return {
        "matchId": str(match.id),
        "matchTitle": f"{match.home_team_name or 'Хозяева'} — {match.away_team_name or 'Гости'}",
        "sport": match.sport_code,
        "league": match.league_name or "Лига не указана",
        "time": starts_at,
        "betKey": "restored",
        "market": prediction.market,
        "selection": prediction.selection,
        "shortLabel": _prediction_short_label(prediction),
        "outcomeCode": prediction.outcome_code,
        "coefficient": _decimal_string(prediction.coefficient),
        "lastSeen": match.last_seen_at.isoformat() if match.last_seen_at else "",
    }


def _prediction_short_label(prediction: Prediction) -> str:
    match = prediction.match
    selection = prediction.selection
    if prediction.market == "winner":
        if selection == "Ничья":
            return "X"
        if selection == match.home_team_name:
            return "1"
        if selection == match.away_team_name:
            return "2"
    if prediction.market == "total":
        return selection[:10]
    if prediction.market == "both_score":
        return "ОЗ"
    return selection[:10]


def _decimal_string(value: Decimal | None) -> str:
    if value is None:
        return ""
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


