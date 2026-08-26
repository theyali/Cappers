from decimal import Decimal

from game.models import Match, Prediction, PredictionCoupon
from game.services.settlement import _normalize, _parse_score, _selection_line, settle_coupon


def settle_live_matches(limit: int = 1000) -> dict:
    """Resolve only live markets whose result can no longer change."""
    matches = (
        Match.objects.filter(sync_scope=Match.SyncScope.LIVE)
        .exclude(score="")
        .order_by("-last_seen_at", "-id")[:limit]
    )
    checked_matches = 0
    updated_predictions = 0
    updated_coupons: set[int] = set()

    for match in matches:
        score = _parse_score(match.score)
        if score is None:
            continue

        checked_matches += 1
        predictions = (
            Prediction.objects.filter(
                match=match,
                coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
                state_status="",
            )
            .select_related("coupon")
        )

        for prediction in predictions:
            state = live_prediction_state(prediction, score)
            if state is None:
                continue

            prediction.state_status = state
            prediction.save(update_fields=["state_status", "updated_at"])
            updated_predictions += 1
            updated_coupons.add(prediction.coupon_id)

    for coupon_id in updated_coupons:
        settle_coupon(coupon_id)

    return {
        "matches": checked_matches,
        "predictions": updated_predictions,
        "coupons": len(updated_coupons),
    }


def live_prediction_state(
    prediction: Prediction,
    score: tuple[int, int],
) -> str | None:
    """Return a result only when the current live score makes it irreversible."""
    market = _normalize(prediction.market)
    selection = _normalize(prediction.selection)

    if market == "total":
        return _live_total_state(selection, sum(score))
    if market == "both_score":
        return _live_both_score_state(selection, score)
    return None


def _live_total_state(selection: str, total_goals: int) -> str | None:
    line = _selection_line(selection)
    if line is None:
        return None

    total = Decimal(total_goals)
    is_over = any(marker in selection for marker in ("тб", "больше", "over"))
    is_under = any(marker in selection for marker in ("тм", "меньше", "under"))

    # Once the score has crossed the line, more goals cannot reverse these outcomes.
    if total > line:
        if is_over:
            return Prediction.StateStatus.WIN
        if is_under:
            return Prediction.StateStatus.LOSE
    return None


def _live_both_score_state(
    selection: str,
    score: tuple[int, int],
) -> str | None:
    if score[0] <= 0 or score[1] <= 0:
        return None

    wants_yes = any(marker in selection for marker in ("да", "yes"))
    wants_no = any(marker in selection for marker in ("нет", "no"))
    if wants_yes:
        return Prediction.StateStatus.WIN
    if wants_no:
        return Prediction.StateStatus.LOSE
    return None
