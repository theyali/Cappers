import logging
from decimal import Decimal

from game.models import Match, Prediction, PredictionCoupon
from game.services.settlement import (
    _is_over_selection,
    _is_under_selection,
    _normalize,
    _parse_score,
    _selection_line,
    settle_coupon,
)
from wallets.services import settle_orphaned_copied_bets


logger = logging.getLogger(__name__)


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

    settlement_errors = 0
    for match in matches:
        try:
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
        except Exception:
            settlement_errors += 1
            logger.exception("Failed to resolve live match #%s.", match.pk)

    for coupon_id in updated_coupons:
        try:
            settle_coupon(coupon_id)
        except Exception:
            settlement_errors += 1
            logger.exception("Failed to settle live coupon #%s.", coupon_id)

    reconciled_copied_bets = settle_orphaned_copied_bets()

    return {
        "matches": checked_matches,
        "predictions": updated_predictions,
        "coupons": len(updated_coupons),
        "reconciled_copied_bets": reconciled_copied_bets,
        "errors": settlement_errors,
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
    is_over = _is_over_selection(selection)
    is_under = _is_under_selection(selection)

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
