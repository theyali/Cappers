import logging
import re
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from cabinet.roulette.rewards import UserRouletteRewardState
from game.models import (
    Match,
    MatchManualReview,
    MatchOdds,
    Prediction,
    PredictionCoupon,
)
from wallets.models import CoinTransaction
from wallets.services import (
    credit_coins,
    settle_copied_bets_for_coupon,
    settle_orphaned_copied_bets,
    settle_prediction_coupon,
)


logger = logging.getLogger(__name__)


VOID_MATCH_SCOPES = {
    Match.SyncScope.POSTPONED,
    Match.SyncScope.CANCELED,
    Match.SyncScope.FORFEIT,
    Match.SyncScope.INTERRUPTED,
    Match.SyncScope.ABANDONED,
}
MONEY_STEP = Decimal("0.01")


def flag_match_for_manual_review(
    match: Match,
    reason: str,
    details: dict | None = None,
) -> MatchManualReview:
    review, created = MatchManualReview.objects.get_or_create(
        match=match,
        reason=reason,
        status=MatchManualReview.Status.OPEN,
        defaults={"details": details or {}},
    )
    if not created and details is not None and review.details != details:
        review.details = details
        review.save(update_fields=["details", "updated_at"])
    return review


def get_match_score_review_reason(match: Match) -> str | None:
    score = (match.score or "").strip()
    if not score:
        return MatchManualReview.Reason.MISSING_SCORE
    parsed_score = _parse_score(score)
    if parsed_score is None:
        return MatchManualReview.Reason.INVALID_SCORE
    if _settlement_score(match, parsed_score) is None:
        return MatchManualReview.Reason.REGULAR_TIME_UNKNOWN
    return None


def resolve_match_manual_reviews(match: Match, reasons: tuple[str, ...]) -> None:
    now = timezone.now()
    MatchManualReview.objects.filter(
        match=match,
        status=MatchManualReview.Status.OPEN,
        reason__in=reasons,
    ).update(
        status=MatchManualReview.Status.RESOLVED,
        resolved_at=now,
        updated_at=now,
    )


def settle_finished_matches(limit: int = 500) -> dict:
    void_result = settle_void_matches(limit=limit)
    matches = (
        Match.objects.filter(sync_scope=Match.SyncScope.FINISHED)
        .select_related("sport")
        .order_by("-starts_at", "-id")[:limit]
    )
    resolved_matches = 0
    updated_predictions = 0
    updated_coupons = set()

    settlement_errors = 0
    for match in matches:
        try:
            predictions = list(
                Prediction.objects.filter(
                    match=match,
                    coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
                    state_status="",
                ).select_related("coupon")
            )
            review_reason = get_match_score_review_reason(match)
            if review_reason == MatchManualReview.Reason.REGULAR_TIME_UNKNOWN and not predictions:
                continue
            if review_reason is not None:
                flag_match_for_manual_review(
                    match,
                    review_reason,
                    {"score": match.score},
                )
                continue

            resolve_match_manual_reviews(
                match,
                (
                    MatchManualReview.Reason.MISSING_SCORE,
                    MatchManualReview.Reason.INVALID_SCORE,
                    MatchManualReview.Reason.REGULAR_TIME_UNKNOWN,
                ),
            )

            result = resolve_match_bets(match)
            if result is None:
                continue

            resolved_matches += 1
            has_unknown_prediction = False
            for prediction in predictions:
                state = prediction_state(prediction, result)
                if state is None:
                    has_unknown_prediction = True
                    flag_match_for_manual_review(
                        match,
                        MatchManualReview.Reason.UNKNOWN_MARKET,
                        {
                            "prediction_id": prediction.id,
                            "market": prediction.market,
                            "selection": prediction.selection,
                        },
                    )
                    continue

                prediction.state_status = state
                prediction.save(update_fields=["state_status", "updated_at"])
                updated_predictions += 1
                updated_coupons.add(prediction.coupon_id)

            if not has_unknown_prediction:
                resolve_match_manual_reviews(
                    match,
                    (MatchManualReview.Reason.UNKNOWN_MARKET,),
                )
            resolve_match_manual_reviews(
                match,
                (MatchManualReview.Reason.SETTLEMENT_ERROR,),
            )
        except Exception as exc:
            settlement_errors += 1
            try:
                flag_match_for_manual_review(
                    match,
                    MatchManualReview.Reason.SETTLEMENT_ERROR,
                    {
                        "error_type": type(exc).__name__,
                        "error": str(exc)[:1000],
                    },
                )
            except Exception:
                logger.exception(
                    "Failed to create manual review for match #%s.",
                    match.pk,
                )
            logger.exception("Failed to resolve finished match #%s.", match.pk)

    for coupon_id in updated_coupons:
        try:
            settle_coupon(coupon_id)
        except Exception:
            settlement_errors += 1
            logger.exception("Failed to settle coupon #%s.", coupon_id)

    reconciled_coupons = reconcile_pending_coupons()
    reconciled_copied_bets = settle_orphaned_copied_bets()

    return {
        "matches": resolved_matches,
        "void_matches": void_result["matches"],
        "predictions": updated_predictions,
        "void_predictions": void_result["predictions"],
        "coupons": len(updated_coupons) + void_result["coupons"],
        "reconciled_coupons": reconciled_coupons,
        "reconciled_copied_bets": reconciled_copied_bets,
        "errors": settlement_errors + void_result["errors"],
    }


def settle_void_matches(limit: int = 500) -> dict:
    matches = (
        Match.objects.filter(sync_scope__in=VOID_MATCH_SCOPES)
        .order_by("-starts_at", "-id")[:limit]
    )
    resolved_matches = 0
    updated_predictions = 0
    updated_coupons: set[int] = set()
    settlement_errors = 0

    for match in matches:
        try:
            predictions = Prediction.objects.filter(
                match=match,
                coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
                state_status="",
            ).select_related("coupon")
            match_updated = False
            for prediction in predictions:
                prediction.state_status = Prediction.StateStatus.REFUND
                prediction.save(update_fields=["state_status", "updated_at"])
                updated_predictions += 1
                updated_coupons.add(prediction.coupon_id)
                match_updated = True

            if match_updated:
                resolved_matches += 1
        except Exception:
            settlement_errors += 1
            logger.exception("Failed to void match #%s.", match.pk)

    for coupon_id in updated_coupons:
        try:
            settle_coupon(coupon_id)
        except Exception:
            settlement_errors += 1
            logger.exception("Failed to settle void coupon #%s.", coupon_id)

    return {
        "matches": resolved_matches,
        "predictions": updated_predictions,
        "coupons": len(updated_coupons),
        "errors": settlement_errors,
    }


@transaction.atomic
def resolve_match_bets(match: Match) -> dict | None:
    if match.sync_scope in VOID_MATCH_SCOPES:
        return None

    score = _parse_score(match.score)
    if score is None:
        return None
    score = _settlement_score(match, score)
    if score is None:
        return None

    home_goals, away_goals = score
    total_goals = _match_total_score(match, score)
    home = match.home_team_name or "Хозяева"
    away = match.away_team_name or "Гости"

    winning = set()
    refunds = set()

    if home_goals > away_goals:
        winning.add(_key("winner", home))
    elif home_goals < away_goals:
        winning.add(_key("winner", away))
    else:
        winning.add(_key("winner", "Ничья"))

    if home_goals >= away_goals:
        winning.add(_key("double_chance", f"{home} или ничья"))
    if away_goals >= home_goals:
        winning.add(_key("double_chance", f"Ничья или {away}"))

    if home_goals == away_goals:
        refunds.add(_key("handicap", f"{home} фора 0"))
        refunds.add(_key("handicap", f"{away} фора 0"))
    elif home_goals > away_goals:
        winning.add(_key("handicap", f"{home} фора 0"))
    else:
        winning.add(_key("handicap", f"{away} фора 0"))

    if home_goals > 0 and away_goals > 0:
        winning.add(_key("both_score", "Обе забьют: да"))
    else:
        winning.add(_key("both_score", "Обе забьют: нет"))

    winning.add(_key("exact_score", f"{home_goals}-{away_goals}"))
    winning.add(_key("exact_score", f"{home_goals}:{away_goals}"))

    for line in _total_lines(match) if total_goals is not None else ():
        over_key = _key("total", f"ТБ {line}")
        under_key = _key("total", f"ТМ {line}")
        if Decimal(total_goals) > line:
            winning.add(over_key)
        elif Decimal(total_goals) < line:
            winning.add(under_key)
        else:
            refunds.update({over_key, under_key})

    first_half_score = _first_half_score(match)
    if first_half_score:
        first_home_goals, first_away_goals = first_half_score
        first_total_goals = first_home_goals + first_away_goals
        if first_home_goals > first_away_goals:
            winning.add(_key("first_half_winner", f"1-й тайм: {home}"))
        elif first_home_goals < first_away_goals:
            winning.add(_key("first_half_winner", f"1-й тайм: {away}"))
        else:
            winning.add(_key("first_half_winner", "1-й тайм: ничья"))

        for line in _first_half_total_lines(match):
            over_key = _key("first_half_total", f"ТБ {line}")
            under_key = _key("first_half_total", f"ТМ {line}")
            if Decimal(first_total_goals) > line:
                winning.add(over_key)
            elif Decimal(first_total_goals) < line:
                winning.add(under_key)
            else:
                refunds.update({over_key, under_key})

    result = {
        "score": match.score,
        "home_goals": home_goals,
        "away_goals": away_goals,
        "total_goals": total_goals,
        "first_half_score": f"{first_half_score[0]}-{first_half_score[1]}" if first_half_score else "",
        "winning": sorted(winning),
        "refunds": sorted(refunds),
        "resolved_at": timezone.now().isoformat(),
    }
    match.winning_bet_keys = result["winning"]
    match.refund_bet_keys = result["refunds"]
    match.odds_result_data = result
    match.odds_resolved_at = timezone.now()
    match.save(
        update_fields=[
            "winning_bet_keys",
            "refund_bet_keys",
            "odds_result_data",
            "odds_resolved_at",
            "updated_at",
        ]
    )
    return result


def prediction_state(prediction: Prediction, result: dict) -> str | None:
    outcome_code = str(getattr(prediction, "outcome_code", "") or "").strip()
    if outcome_code:
        return _settle_by_outcome_code(prediction, outcome_code, result)

    # Predictions saved before outcome codes existed are settled by their text.
    evaluated = _evaluate_prediction(prediction, result)
    if evaluated is not None:
        return evaluated

    key = _key(prediction.market, prediction.selection)
    if key in set(result.get("refunds") or []):
        return Prediction.StateStatus.REFUND
    if key in set(result.get("winning") or []):
        return Prediction.StateStatus.WIN

    return None


@transaction.atomic
def settle_coupon(coupon_id: int) -> PredictionCoupon | None:
    coupon = PredictionCoupon.objects.prefetch_related("predictions").filter(pk=coupon_id).first()
    if coupon is None:
        return None

    predictions = list(coupon.predictions.all())
    states = [prediction.state_status for prediction in predictions]
    effective_payout = _effective_coupon_payout(coupon, predictions)
    if Prediction.StateStatus.LOSE in states:
        coupon.state_status = PredictionCoupon.StateStatus.LOSE
        coupon.settled_at = coupon.settled_at or timezone.now()
    elif not states or any(not state for state in states):
        coupon.state_status = PredictionCoupon.StateStatus.PENDING
        coupon.settled_at = None
    elif any(state == Prediction.StateStatus.WIN for state in states):
        coupon.state_status = PredictionCoupon.StateStatus.WIN
        coupon.settled_at = coupon.settled_at or timezone.now()
    else:
        coupon.state_status = PredictionCoupon.StateStatus.REFUND
        coupon.settled_at = coupon.settled_at or timezone.now()

    if effective_payout is not None:
        coupon.possible_payout = effective_payout

    update_fields = ["state_status", "settled_at", "updated_at"]
    if effective_payout is not None:
        update_fields.append("possible_payout")
    coupon.save(update_fields=update_fields)
    settle_prediction_coupon(coupon)
    return coupon


@transaction.atomic
def cancel_published_coupon(coupon_id: int, *, reason: str = "") -> PredictionCoupon:
    """Withdraw a published, not yet settled coupon and return every stake taken for it.

    The author gets the stake back (or the free roulette prediction it was paid
    with), and copy-betting followers get their copied stakes refunded. Authors
    cannot unpublish coupons themselves; this service is the only way to void one.
    """
    coupon = (
        PredictionCoupon.objects.select_for_update()
        .select_related("author")
        .filter(pk=coupon_id)
        .first()
    )
    if coupon is None:
        raise ValidationError("Прогноз не найден.")
    if coupon.published_status != PredictionCoupon.PublishedStatus.PUBLISHED:
        raise ValidationError("Отменить можно только опубликованный прогноз.")
    if coupon.state_status != PredictionCoupon.StateStatus.PENDING:
        raise ValidationError("Рассчитанный прогноз отменить нельзя.")

    coupon.published_status = PredictionCoupon.PublishedStatus.CANCELED
    coupon.save(update_fields=["published_status", "updated_at"])
    _refund_author_stake(coupon, reason=reason)
    settle_copied_bets_for_coupon(coupon, outcome=PredictionCoupon.StateStatus.REFUND)
    return coupon


def _refund_author_stake(coupon: PredictionCoupon, *, reason: str) -> None:
    stake_transaction = (
        CoinTransaction.objects.filter(
            user_id=coupon.author_id,
            kind=CoinTransaction.Kind.PREDICTION_STAKE,
            related_model=coupon._meta.label_lower,
            related_id=coupon.pk,
        )
        .order_by("id")
        .first()
    )
    if stake_transaction is None:
        return

    if stake_transaction.amount < 0:
        note = f"Возврат ставки отменённого прогноза #{coupon.pk}"
        credit_coins(
            coupon.author,
            abs(stake_transaction.amount),
            CoinTransaction.Kind.PREDICTION_REFUND,
            related_obj=coupon,
            note=f"{note}: {reason}" if reason else note,
        )
        return

    # A zero stake transaction means the coupon was paid with a free roulette prediction.
    reward_state, _ = UserRouletteRewardState.objects.select_for_update().get_or_create(
        user_id=coupon.author_id,
    )
    reward_state.free_predictions += 1
    reward_state.save(update_fields=("free_predictions", "updated_at"))


def resettle_coupon(
    coupon_id: int,
    *,
    recalculate_predictions: bool = True,
) -> PredictionCoupon | None:
    coupon = PredictionCoupon.objects.filter(pk=coupon_id).first()
    if coupon is None:
        return None

    if recalculate_predictions:
        predictions = Prediction.objects.filter(coupon=coupon).select_related("match")
        for prediction in predictions:
            if prediction.match.sync_scope in VOID_MATCH_SCOPES:
                state = Prediction.StateStatus.REFUND
                if prediction.state_status != state:
                    prediction.state_status = state
                    prediction.save(update_fields=["state_status", "updated_at"])
                continue

            review_reason = get_match_score_review_reason(prediction.match)
            if review_reason is not None:
                flag_match_for_manual_review(
                    prediction.match,
                    review_reason,
                    {"score": prediction.match.score},
                )
                if prediction.state_status:
                    prediction.state_status = ""
                    prediction.save(update_fields=["state_status", "updated_at"])
                continue

            result = resolve_match_bets(prediction.match)
            if result is None:
                continue
            state = prediction_state(prediction, result)
            if state is None:
                flag_match_for_manual_review(
                    prediction.match,
                    MatchManualReview.Reason.UNKNOWN_MARKET,
                    {
                        "prediction_id": prediction.id,
                        "market": prediction.market,
                        "selection": prediction.selection,
                    },
                )
                if prediction.state_status:
                    prediction.state_status = ""
                    prediction.save(update_fields=["state_status", "updated_at"])
                continue
            if prediction.state_status != state:
                prediction.state_status = state
                prediction.save(update_fields=["state_status", "updated_at"])

    return settle_coupon(coupon_id)


def _effective_coupon_payout(
    coupon: PredictionCoupon,
    predictions: list[Prediction],
) -> Decimal | None:
    if not predictions:
        return None

    states = [prediction.state_status for prediction in predictions]
    if any(not state for state in states):
        return None

    stake = coupon.total_stake or Decimal("0")
    if stake <= 0:
        return Decimal("0.00")

    total_coefficient = Decimal("1")
    has_active_position = False
    for prediction in predictions:
        if prediction.state_status == Prediction.StateStatus.REFUND:
            continue
        coefficient = prediction.coefficient or Decimal("0")
        if coefficient <= 0:
            continue
        total_coefficient *= coefficient
        has_active_position = True

    if not has_active_position:
        return stake.quantize(MONEY_STEP)
    return (stake * total_coefficient).quantize(MONEY_STEP)


def reconcile_pending_coupons(limit: int = 1000) -> int:
    coupon_ids = (
        PredictionCoupon.objects.filter(
            published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            state_status=PredictionCoupon.StateStatus.PENDING,
        )
        .values_list("id", flat=True)
        .order_by("-published_at", "-created_at")[:limit]
    )
    reconciled = 0
    for coupon_id in coupon_ids:
        try:
            coupon = settle_coupon(coupon_id)
            if coupon and coupon.state_status != PredictionCoupon.StateStatus.PENDING:
                reconciled += 1
        except Exception:
            logger.exception("Failed to reconcile pending coupon #%s.", coupon_id)
    return reconciled


def _parse_score(value: str) -> tuple[int, int] | None:
    numbers = re.findall(r"\d+", value or "")
    if len(numbers) < 2:
        return None
    return int(numbers[0]), int(numbers[1])


def _parse_optional_score(value: str | None) -> tuple[int, int] | None:
    if not value:
        return None
    return _parse_score(value)


def _settle_by_outcome_code(prediction: Prediction, outcome_code: str, result: dict) -> str | None:
    market = _normalize(prediction.market)
    match = prediction.match
    if market.startswith("first_half_"):
        score = _first_half_score(match)
        if score is None:
            return None
        total = sum(score)
        market = market.removeprefix("first_half_")
    else:
        score = (int(result["home_goals"]), int(result["away_goals"]))
        total = result["total_goals"] if "total_goals" in result else _match_total_score(match, score)

    home_goals, away_goals = score
    winner_code = "1" if home_goals > away_goals else "2" if home_goals < away_goals else "X"

    if market == "winner":
        return _state(outcome_code == winner_code)
    if market == "double_chance":
        return _state(winner_code in outcome_code)
    if market == "both_score":
        both_scored = home_goals > 0 and away_goals > 0
        return _state(both_scored == (outcome_code == "yes"))
    if market == "exact_score":
        selected = _parse_optional_score(outcome_code)
        return _state(selected == score) if selected else None

    side, _, raw_line = outcome_code.partition(" ")
    try:
        line = Decimal(raw_line)
    except InvalidOperation:
        return None
    if market == "total":
        if total is None:
            return None
        if Decimal(total) == line:
            return Prediction.StateStatus.REFUND
        return _state((Decimal(total) > line) == (side == "over"))
    if market == "handicap":
        own, opponent = (home_goals, away_goals) if side == "home" else (away_goals, home_goals)
        adjusted = Decimal(own) + line
        if adjusted == opponent:
            return Prediction.StateStatus.REFUND
        return _state(adjusted > opponent)
    return None


def _state(won: bool) -> str:
    return Prediction.StateStatus.WIN if won else Prediction.StateStatus.LOSE


def _evaluate_prediction(prediction: Prediction, result: dict) -> str | None:
    score = (
        int(result["home_goals"]),
        int(result["away_goals"]),
    )
    market = _normalize(prediction.market)
    selection = _normalize(prediction.selection)
    match = prediction.match
    home_name = _normalize(match.home_team_name or "Хозяева")
    away_name = _normalize(match.away_team_name or "Гости")

    if market in {"winner", "1x2", "match_winner", "match winner", "победитель", "исход"}:
        return _settle_winner(selection, score, home_name, away_name)
    if market in {"double_chance", "double chance", "двойной шанс"}:
        return _settle_double_chance(selection, score, home_name, away_name)
    if market in {"total", "totals", "match_total", "match total", "total_goals", "goals_total", "тотал"}:
        return _settle_total(selection, _match_total_score(match, score))
    if market in {"both_score", "both score", "btts", "обе забьют"}:
        return _settle_both_score(selection, score)
    if market in {"handicap", "spread", "фора"}:
        return _settle_handicap(selection, score, home_name, away_name)
    if market in {"exact_score", "exact score", "точный счет", "точный счёт"}:
        return _settle_exact_score(selection, score)

    first_half_score = _first_half_score(match)
    if market in {"first_half_winner", "first half winner", "1-й тайм исход"} and first_half_score:
        return _settle_winner(selection, first_half_score, home_name, away_name)
    if market in {"first_half_total", "first half total", "тотал 1-го тайма"} and first_half_score:
        return _settle_total(selection, sum(first_half_score))
    if market in {"first_half_handicap", "first half handicap", "фора 1-го тайма"} and first_half_score:
        return _settle_handicap(selection, first_half_score, home_name, away_name)
    return None


def _team_side(text: str, home_name: str, away_name: str) -> str | None:
    """Which team a selection text names.

    An exact name wins; otherwise the longest contained name does, so
    "динамо москва" is the away side even when the home team is "динамо".
    """
    if text in {home_name, "1", "home", "хозяева", "п1"}:
        return "home"
    if text in {away_name, "2", "away", "гости", "п2"}:
        return "away"
    candidates = [
        (len(name), side)
        for name, side in ((home_name, "home"), (away_name, "away"))
        if name and name in text
    ]
    return max(candidates)[1] if candidates else None


def _settle_winner(
    selection: str,
    score: tuple[int, int],
    home_name: str,
    away_name: str,
) -> str | None:
    home_goals, away_goals = score
    if selection in {"x", "draw", "ничья"}:
        return Prediction.StateStatus.WIN if home_goals == away_goals else Prediction.StateStatus.LOSE
    side = _team_side(selection, home_name, away_name)
    if side == "home":
        return Prediction.StateStatus.WIN if home_goals > away_goals else Prediction.StateStatus.LOSE
    if side == "away":
        return Prediction.StateStatus.WIN if away_goals > home_goals else Prediction.StateStatus.LOSE
    return None


def _settle_double_chance(
    selection: str,
    score: tuple[int, int],
    home_name: str,
    away_name: str,
) -> str | None:
    home_goals, away_goals = score
    home_or_draw = home_goals >= away_goals
    away_or_draw = away_goals >= home_goals
    home_or_away = home_goals != away_goals

    if selection in {"1x", "home or draw", "хозяева или ничья"}:
        return Prediction.StateStatus.WIN if home_or_draw else Prediction.StateStatus.LOSE
    if selection in {"x2", "draw or away", "ничья или гости"}:
        return Prediction.StateStatus.WIN if away_or_draw else Prediction.StateStatus.LOSE
    if selection in {"12", "home or away", "хозяева или гости"}:
        return Prediction.StateStatus.WIN if home_or_away else Prediction.StateStatus.LOSE

    parts = [part.strip() for part in selection.split(" или ")]
    if len(parts) != 2:
        return None
    sides = {_team_side(part, home_name, away_name) for part in parts if not part.startswith("нич")}
    if "нич" in selection and sides == {"home"}:
        return Prediction.StateStatus.WIN if home_or_draw else Prediction.StateStatus.LOSE
    if "нич" in selection and sides == {"away"}:
        return Prediction.StateStatus.WIN if away_or_draw else Prediction.StateStatus.LOSE
    if sides == {"home", "away"}:
        return Prediction.StateStatus.WIN if home_or_away else Prediction.StateStatus.LOSE
    return None


def _settle_total(selection: str, total_goals: int | None) -> str | None:
    line = _selection_line(selection)
    if line is None or total_goals is None:
        return None
    is_over = _is_over_selection(selection)
    is_under = _is_under_selection(selection)
    if not is_over and not is_under:
        return None
    if Decimal(total_goals) == line:
        return Prediction.StateStatus.REFUND
    if is_over:
        return Prediction.StateStatus.WIN if Decimal(total_goals) > line else Prediction.StateStatus.LOSE
    return Prediction.StateStatus.WIN if Decimal(total_goals) < line else Prediction.StateStatus.LOSE


def _settle_both_score(selection: str, score: tuple[int, int]) -> str | None:
    both_scored = score[0] > 0 and score[1] > 0
    wants_yes = any(marker in selection for marker in ("да", "yes"))
    wants_no = any(marker in selection for marker in ("нет", "no"))
    if wants_yes:
        return Prediction.StateStatus.WIN if both_scored else Prediction.StateStatus.LOSE
    if wants_no:
        return Prediction.StateStatus.WIN if not both_scored else Prediction.StateStatus.LOSE
    return None


def _settle_handicap(
    selection: str,
    score: tuple[int, int],
    home_name: str,
    away_name: str,
) -> str | None:
    line = _selection_line(selection)
    if line is None:
        return None

    side = _team_side(re.sub(r"\s*фора.*$", "", selection), home_name, away_name)
    if side is None:
        if "ф1" in selection or "home" in selection or "хозяева" in selection:
            side = "home"
        elif "ф2" in selection or "away" in selection or "гости" in selection:
            side = "away"
    if side is None:
        return None

    adjusted = Decimal(score[0] if side == "home" else score[1]) + line
    opponent = Decimal(score[1] if side == "home" else score[0])
    if adjusted == opponent:
        return Prediction.StateStatus.REFUND
    return Prediction.StateStatus.WIN if adjusted > opponent else Prediction.StateStatus.LOSE


def _settle_exact_score(selection: str, score: tuple[int, int]) -> str | None:
    numbers = re.findall(r"\d+", selection)
    if len(numbers) < 2:
        return None
    selected_score = (int(numbers[0]), int(numbers[1]))
    return Prediction.StateStatus.WIN if selected_score == score else Prediction.StateStatus.LOSE


def _first_half_score(match: Match) -> tuple[int, int] | None:
    payload = match.raw_data if isinstance(match.raw_data, dict) else {}
    direct_score = _parse_optional_score(
        str(
            payload.get("first_time_score")
            or payload.get("first_half_score")
            or payload.get("ht_score")
            or ""
        )
    )
    if direct_score:
        return direct_score

    periods = payload.get("periods") or payload.get("scoreboard") or {}
    if isinstance(periods, dict):
        for key in ("1H", "1h", "first_half", "first_time", "period_1"):
            score = _parse_optional_score(str(periods.get(key) or ""))
            if score:
                return score
    return None


def _match_total_score(match: Match, score: tuple[int, int]) -> int | None:
    """Total for totals markets: tennis counts games of the sets, other sports the score."""
    if _sport_code(match) == "tennis":
        return _tennis_games_total(match)
    return sum(score)


def _settlement_score(match: Match, score: tuple[int, int]) -> tuple[int, int] | None:
    """Score markets are settled by.

    Hockey lines are three-way and settled by regular time: overtime goals and
    the shootout goal are excluded. The regular-time score comes from the field
    an admin fills during manual review, then from period scores; without them
    it is still known unless the final margin is one goal (a possible overtime).
    """
    if _sport_code(match) != "hockey":
        return score
    regular = _parse_optional_score(getattr(match, "regular_time_score", "")) or hockey_regular_time_score(match)
    if regular is not None:
        return regular
    if abs(score[0] - score[1]) != 1:
        return score
    return None


def hockey_regular_time_score(match: Match, *, partial: bool = False) -> tuple[int, int] | None:
    """Sum of the three regulation periods; ``partial`` allows periods not played yet (live)."""
    payload = match.raw_data if isinstance(match.raw_data, dict) else {}
    periods = payload.get("periods")
    if not isinstance(periods, dict):
        return None

    if any(key in periods for key in ("first", "second", "third")):
        period_scores = [_parse_optional_score(str(periods.get(key) or "")) for key in ("first", "second", "third")]
    else:
        items = periods.get("items") if isinstance(periods.get("items"), list) else []
        by_number = {
            int(item.get("number")): _score_from_mapping(item.get("score") or {})
            for item in items
            if isinstance(item, dict)
            and str(item.get("type") or "").lower() == "period"
            and str(item.get("number") or "").isdigit()
        }
        period_scores = [by_number.get(number) for number in (1, 2, 3)]

    known = [period_score for period_score in period_scores if period_score is not None]
    if not known or (not partial and len(known) != 3):
        return None
    return sum(home for home, _ in known), sum(away for _, away in known)


def _tennis_games_total(match: Match) -> int | None:
    payload = match.raw_data if isinstance(match.raw_data, dict) else {}
    set_scores = []
    periods = payload.get("periods")
    items = periods.get("items") if isinstance(periods, dict) else None
    for item in items if isinstance(items, list) else []:
        # Only sets count: the "POINT" item holds the current rally score (15/30/40).
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "").lower() != "set" and not re.fullmatch(r"S\d+", str(item.get("code") or "")):
            continue
        set_score = _score_from_mapping(item.get("score") or {})
        if set_score is not None:
            set_scores.append(set_score)

    if not set_scores:
        legacy_sets = payload.get("sets")
        values = legacy_sets.values() if isinstance(legacy_sets, dict) else legacy_sets
        for value in values if isinstance(values, (list, tuple, type({}.values()))) else []:
            set_score = (
                _score_from_mapping(value)
                if isinstance(value, dict)
                else _parse_optional_score(str(value or ""))
            )
            if set_score is not None:
                set_scores.append(set_score)

    if not set_scores:
        return None
    return sum(home + away for home, away in set_scores)


def _sport_code(match) -> str:
    if getattr(match, "sport_id", None):
        return str(match.sport_code or "football").lower()
    payload = match.raw_data if isinstance(getattr(match, "raw_data", None), dict) else {}
    sport_codes = {sport["id"]: sport["code"] for sport in settings.NEUROKEFF_SPORTS}
    try:
        return sport_codes.get(int(payload.get("sport_id")), "football")
    except (TypeError, ValueError):
        return str(getattr(match, "sport_code", "") or "football").lower()


def _score_from_mapping(payload: dict) -> tuple[int, int] | None:
    home = _first_mapping_value(payload, ("home", "home_score", "home_goals", "team_1"))
    away = _first_mapping_value(payload, ("away", "away_score", "away_goals", "team_2"))
    home_score = _score_part(home)
    away_score = _score_part(away)
    if home_score is None or away_score is None:
        return None
    return home_score, away_score


def _first_mapping_value(payload: dict, keys: tuple[str, ...]):
    for key in keys:
        if key in payload:
            return payload[key]
    return None


def _score_part(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _selection_line(selection: str) -> Decimal | None:
    numbers = re.findall(r"[-+]?\d+(?:[.,]\d+)?", selection)
    if not numbers:
        return None
    try:
        return Decimal(numbers[-1].replace(",", "."))
    except InvalidOperation:
        return None


def _is_over_selection(selection: str) -> bool:
    return bool(
        re.search(r"(^|[\s(:])(?:тб|больше|over|o)(?=\s*\d|\s|$)", selection)
        or "тотал больше" in selection
    )


def _is_under_selection(selection: str) -> bool:
    return bool(
        re.search(r"(^|[\s(:])(?:тм|меньше|under|u)(?=\s*\d|\s|$)", selection)
        or "тотал меньше" in selection
    )


def _total_lines(match: Match) -> set[Decimal]:
    lines = {Decimal("2.5")}
    try:
        totals = match.odds.totals_all
    except MatchOdds.DoesNotExist:
        totals = {}
    lines.update(_lines_from_payload(totals))
    return lines


def _first_half_total_lines(match: Match) -> set[Decimal]:
    lines = {Decimal("2.5")}
    try:
        totals = match.odds.first_half_totals_all
    except MatchOdds.DoesNotExist:
        totals = {}
    lines.update(_lines_from_payload(totals))
    return lines


def _lines_from_payload(totals: dict) -> set[Decimal]:
    lines = set()
    if isinstance(totals, dict):
        for key in totals:
            number = re.search(r"\d+(?:[.,]\d+)?", str(key))
            if number:
                try:
                    lines.add(Decimal(number.group(0).replace(",", ".")))
                except InvalidOperation:
                    continue
    return lines


def _key(market: str, selection: str) -> str:
    return f"{_normalize(market)}:{_normalize(selection)}"


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())
