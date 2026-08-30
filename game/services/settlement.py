import re
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from game.models import Match, MatchOdds, Prediction, PredictionCoupon
from wallets.services import settle_prediction_coupon


def settle_finished_matches(limit: int = 500) -> dict:
    matches = (
        Match.objects.filter(sync_scope=Match.SyncScope.FINISHED)
        .exclude(score="")
        .order_by("-starts_at", "-id")[:limit]
    )
    resolved_matches = 0
    updated_predictions = 0
    updated_coupons = set()

    for match in matches:
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

    for coupon_id in updated_coupons:
        settle_coupon(coupon_id)

    reconciled_coupons = reconcile_pending_coupons()

    return {
        "matches": resolved_matches,
        "predictions": updated_predictions,
        "coupons": len(updated_coupons),
        "reconciled_coupons": reconciled_coupons,
    }


@transaction.atomic
def resolve_match_bets(match: Match) -> dict | None:
    score = _parse_score(match.score)
    if score is None:
        return None

    home_goals, away_goals = score
    total_goals = home_goals + away_goals
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
    key = _key(prediction.market, prediction.selection)
    if key in set(result.get("refunds") or []):
        return Prediction.StateStatus.REFUND
    if key in set(result.get("winning") or []):
        return Prediction.StateStatus.WIN

    evaluated = _evaluate_prediction(prediction, result)
    if evaluated is not None:
        return evaluated
    return Prediction.StateStatus.LOSE


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
        coupon = settle_coupon(coupon_id)
        if coupon and coupon.state_status != PredictionCoupon.StateStatus.PENDING:
            reconciled += 1
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

    if market == "winner":
        return _settle_winner(selection, score, home_name, away_name)
    if market == "double_chance":
        return _settle_double_chance(selection, score, home_name, away_name)
    if market == "total":
        return _settle_total(selection, sum(score))
    if market == "both_score":
        return _settle_both_score(selection, score)
    if market == "handicap":
        return _settle_handicap(selection, score, home_name, away_name)
    if market == "exact_score":
        return _settle_exact_score(selection, score)

    first_half_score = _first_half_score(match)
    if market == "first_half_winner" and first_half_score:
        return _settle_winner(selection, first_half_score, home_name, away_name)
    if market == "first_half_total" and first_half_score:
        return _settle_total(selection, sum(first_half_score))
    if market == "first_half_handicap" and first_half_score:
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
    is_over = any(marker in selection for marker in ("тб", "больше", "over"))
    is_under = any(marker in selection for marker in ("тм", "меньше", "under"))
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


def _selection_line(selection: str) -> Decimal | None:
    numbers = re.findall(r"[-+]?\d+(?:[.,]\d+)?", selection)
    if not numbers:
        return None
    try:
        return Decimal(numbers[-1].replace(",", "."))
    except InvalidOperation:
        return None


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
