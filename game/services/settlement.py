import logging
import re
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from game.models import Match, MatchOdds, Prediction, PredictionCoupon
from wallets.services import settle_orphaned_copied_bets, settle_prediction_coupon


logger = logging.getLogger(__name__)


def settle_finished_matches(limit: int = 500) -> dict:
    matches = (
        Match.objects.filter(sync_scope=Match.SyncScope.FINISHED)
        .exclude(score="")
        .order_by("-starts_at", "-id")[:limit]
    )
    resolved_matches = 0
    updated_predictions = 0
    updated_coupons = set()

    settlement_errors = 0
    for match in matches:
        try:
            result = resolve_match_bets(match)
            if result is None:
                continue

            resolved_matches += 1
            predictions = Prediction.objects.filter(
                match=match,
                coupon__published_status=PredictionCoupon.PublishedStatus.PUBLISHED,
            ).filter(state_status="")

            for prediction in predictions.select_related("coupon"):
                state = prediction_state(prediction, result)
                prediction.state_status = state
                prediction.save(update_fields=["state_status", "updated_at"])
                updated_predictions += 1
                updated_coupons.add(prediction.coupon_id)
        except Exception:
            settlement_errors += 1
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
        "predictions": updated_predictions,
        "coupons": len(updated_coupons),
        "reconciled_coupons": reconciled_coupons,
        "reconciled_copied_bets": reconciled_copied_bets,
        "errors": settlement_errors,
    }


@transaction.atomic
def resolve_match_bets(match: Match) -> dict | None:
    score = _parse_score(match.score)
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

    for line in _total_lines(match):
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


def prediction_state(prediction: Prediction, result: dict) -> str:
    evaluated = _evaluate_prediction(prediction, result)
    if evaluated is not None:
        return evaluated

    key = _key(prediction.market, prediction.selection)
    if key in set(result.get("refunds") or []):
        return Prediction.StateStatus.REFUND
    if key in set(result.get("winning") or []):
        return Prediction.StateStatus.WIN

    return Prediction.StateStatus.LOSE


@transaction.atomic
def settle_coupon(coupon_id: int) -> PredictionCoupon | None:
    coupon = PredictionCoupon.objects.filter(pk=coupon_id).first()
    if coupon is None:
        return None

    states = list(coupon.predictions.values_list("state_status", flat=True))
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

    coupon.save(update_fields=["state_status", "settled_at", "updated_at"])
    settle_prediction_coupon(coupon)
    return coupon


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
            result = resolve_match_bets(prediction.match)
            if result is None:
                continue
            state = prediction_state(prediction, result)
            if prediction.state_status != state:
                prediction.state_status = state
                prediction.save(update_fields=["state_status", "updated_at"])

    return settle_coupon(coupon_id)


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


def _settle_winner(
    selection: str,
    score: tuple[int, int],
    home_name: str,
    away_name: str,
) -> str:
    home_goals, away_goals = score
    if selection in {"1", "home", "хозяева"} or selection == home_name or home_name in selection:
        return Prediction.StateStatus.WIN if home_goals > away_goals else Prediction.StateStatus.LOSE
    if selection in {"2", "away", "гости"} or selection == away_name or away_name in selection:
        return Prediction.StateStatus.WIN if away_goals > home_goals else Prediction.StateStatus.LOSE
    if selection in {"x", "draw", "ничья"}:
        return Prediction.StateStatus.WIN if home_goals == away_goals else Prediction.StateStatus.LOSE
    return Prediction.StateStatus.LOSE


def _settle_double_chance(
    selection: str,
    score: tuple[int, int],
    home_name: str,
    away_name: str,
) -> str:
    home_goals, away_goals = score
    home_or_draw = home_goals >= away_goals
    away_or_draw = away_goals >= home_goals
    home_or_away = home_goals != away_goals

    if selection in {"1x", "home or draw", "хозяева или ничья"} or (
        home_name in selection and "нич" in selection
    ):
        return Prediction.StateStatus.WIN if home_or_draw else Prediction.StateStatus.LOSE
    if selection in {"x2", "draw or away", "ничья или гости"} or (
        away_name in selection and "нич" in selection
    ):
        return Prediction.StateStatus.WIN if away_or_draw else Prediction.StateStatus.LOSE
    if selection in {"12", "home or away", "хозяева или гости"} or (
        home_name in selection and away_name in selection
    ):
        return Prediction.StateStatus.WIN if home_or_away else Prediction.StateStatus.LOSE
    return Prediction.StateStatus.LOSE


def _settle_total(selection: str, total_goals: int) -> str:
    line = _selection_line(selection)
    if line is None:
        return Prediction.StateStatus.LOSE
    is_over = _is_over_selection(selection)
    is_under = _is_under_selection(selection)
    if Decimal(total_goals) == line:
        return Prediction.StateStatus.REFUND
    if is_over:
        return Prediction.StateStatus.WIN if Decimal(total_goals) > line else Prediction.StateStatus.LOSE
    if is_under:
        return Prediction.StateStatus.WIN if Decimal(total_goals) < line else Prediction.StateStatus.LOSE
    return Prediction.StateStatus.LOSE


def _settle_both_score(selection: str, score: tuple[int, int]) -> str:
    both_scored = score[0] > 0 and score[1] > 0
    wants_yes = any(marker in selection for marker in ("да", "yes"))
    wants_no = any(marker in selection for marker in ("нет", "no"))
    if wants_yes:
        return Prediction.StateStatus.WIN if both_scored else Prediction.StateStatus.LOSE
    if wants_no:
        return Prediction.StateStatus.WIN if not both_scored else Prediction.StateStatus.LOSE
    return Prediction.StateStatus.LOSE


def _settle_handicap(
    selection: str,
    score: tuple[int, int],
    home_name: str,
    away_name: str,
) -> str:
    line = _selection_line(selection)
    if line is None:
        line = Decimal("0")

    side = None
    if home_name in selection or "ф1" in selection or "home" in selection or "хозяева" in selection:
        side = "home"
    elif away_name in selection or "ф2" in selection or "away" in selection or "гости" in selection:
        side = "away"

    if side is None:
        return Prediction.StateStatus.LOSE

    adjusted = Decimal(score[0] if side == "home" else score[1]) + line
    opponent = Decimal(score[1] if side == "home" else score[0])
    if adjusted == opponent:
        return Prediction.StateStatus.REFUND
    return Prediction.StateStatus.WIN if adjusted > opponent else Prediction.StateStatus.LOSE


def _settle_exact_score(selection: str, score: tuple[int, int]) -> str:
    numbers = re.findall(r"\d+", selection)
    if len(numbers) < 2:
        return Prediction.StateStatus.LOSE
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


def _match_total_score(match: Match, score: tuple[int, int]) -> int:
    score_total = sum(score)
    period_total = _period_score_total(match)
    return max(score_total, period_total or 0)


def _period_score_total(match: Match) -> int | None:
    payload = match.raw_data if isinstance(match.raw_data, dict) else {}
    totals = [
        total
        for key in ("periods", "scoreboard", "scores", "period_scores", "sets", "quarters")
        if (total := _sum_score_payload(payload.get(key))) is not None
    ]
    return max(totals) if totals else None


def _sum_score_payload(payload) -> int | None:
    if payload in (None, ""):
        return None

    if isinstance(payload, str):
        score = _parse_optional_score(payload)
        return sum(score) if score else None

    if isinstance(payload, dict):
        direct_score = _score_from_mapping(payload)
        if direct_score is not None:
            return sum(direct_score)
        totals = [
            total
            for value in payload.values()
            if (total := _sum_score_payload(value)) is not None
        ]
        return sum(totals) if totals else None

    if isinstance(payload, (list, tuple)):
        totals = [
            total
            for value in payload
            if (total := _sum_score_payload(value)) is not None
        ]
        return sum(totals) if totals else None

    return None


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
