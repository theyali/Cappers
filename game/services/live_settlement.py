import logging
from decimal import Decimal, InvalidOperation

from game.models import Match, Prediction, PredictionCoupon
from game.services.settlement import (
    _is_over_selection,
    _is_under_selection,
    _normalize,
    _parse_score,
    _selection_line,
    _sport_code,
    hockey_regular_time_score,
    settle_coupon,
)
from wallets.services import settle_orphaned_copied_bets


logger = logging.getLogger(__name__)

# A goal cancelled by VAR (or a scoring correction) must not reverse a live
# result: settle only when the outcome holds even without this many goals/points.
LIVE_SAFETY_MARGIN = {"basketball": 3}
DEFAULT_LIVE_SAFETY_MARGIN = 1


def settle_live_matches(limit: int = 1000) -> dict:
    """Resolve only live markets whose result can no longer change."""
    matches = (
        Match.objects.filter(sync_scope=Match.SyncScope.LIVE)
        .exclude(score="")
        .select_related("sport")
        .order_by("-last_seen_at", "-id")[:limit]
    )
    checked_matches = 0
    updated_predictions = 0
    updated_coupons: set[int] = set()

    settlement_errors = 0
    for match in matches:
        try:
            score = _live_settlement_score(match)
            if score is None:
                continue
            sport_code = _sport_code(match)

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
                state = live_prediction_state(prediction, score, sport_code=sport_code)
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


def _live_settlement_score(match: Match) -> tuple[int, int] | None:
    score = _parse_score(match.score)
    if score is None:
        return None
    sport_code = _sport_code(match)
    if sport_code == "tennis":
        # The live tennis score counts sets, while totals count games.
        return None
    if sport_code == "hockey":
        # Hockey is settled by regular time; overtime goals must not count.
        return hockey_regular_time_score(match, partial=True)
    return score


def live_prediction_state(
    prediction: Prediction,
    score: tuple[int, int],
    *,
    sport_code: str = "football",
) -> str | None:
    """Return a result only when the current live score makes it irreversible."""
    margin = LIVE_SAFETY_MARGIN.get(sport_code, DEFAULT_LIVE_SAFETY_MARGIN)
    market = _normalize(prediction.market)
    outcome_code = str(getattr(prediction, "outcome_code", "") or "").strip()

    if market == "total":
        side, line = _total_outcome(prediction, outcome_code)
        if side is None or line is None:
            return None
        # Once the score is past the line even without `margin` goals, more goals
        # cannot reverse the outcome.
        if Decimal(sum(score) - margin) > line:
            return Prediction.StateStatus.WIN if side == "over" else Prediction.StateStatus.LOSE
        return None

    if market == "both_score":
        wants_yes = _wants_both_score(prediction, outcome_code)
        if wants_yes is None or min(score) - margin < 1:
            return None
        return Prediction.StateStatus.WIN if wants_yes else Prediction.StateStatus.LOSE

    return None


def _total_outcome(prediction: Prediction, outcome_code: str) -> tuple[str | None, Decimal | None]:
    if outcome_code:
        side, _, raw_line = outcome_code.partition(" ")
        try:
            return side, Decimal(raw_line)
        except InvalidOperation:
            return None, None

    selection = _normalize(prediction.selection)
    side = "over" if _is_over_selection(selection) else "under" if _is_under_selection(selection) else None
    return side, _selection_line(selection)


def _wants_both_score(prediction: Prediction, outcome_code: str) -> bool | None:
    if outcome_code in {"yes", "no"}:
        return outcome_code == "yes"
    selection = _normalize(prediction.selection)
    if any(marker in selection for marker in ("да", "yes")):
        return True
    if any(marker in selection for marker in ("нет", "no")):
        return False
    return None
